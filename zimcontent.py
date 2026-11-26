"""Article content + link extraction from a local Kiwix ZIM archive.

Wikilinks v1.2 serves article pages itself (instead of live simple.wikipedia.org)
so every link click is observable server-side. Content comes from a downloaded
Kiwix ZIM snapshot of Simple English Wikipedia (see setup.sh) rather than a
live fetch, so gameplay has no runtime dependency on Wikipedia's servers.

Internal links inside ZIM article HTML are relative paths into the same
archive. The exact scheme (namespaced `A/Title` vs a flat `Title`, `../`
prefixing, percent-encoding) depends on the exact ZIM build; `_clean_href`
normalises the common forms. If link rewriting misbehaves against a real
downloaded file, that normalisation is the first place to adjust.
"""
import re
from html.parser import HTMLParser
from urllib.parse import unquote
from libzim.reader import Archive

_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
         'link', 'meta', 'param', 'source', 'track', 'wbr'}
_SKIP_PREFIX = re.compile(r'^(?:\.\./|\./)+')
_NS_PREFIX = re.compile(r'^[A-Za-z]/')
# A denylist rather than an "looks like it has an extension" heuristic:
# plenty of real article titles end in something extension-shaped
# (Amazon.com, Match.com, ...), so guessing by pattern is unsafe.
_ASSET_EXT = re.compile(
    r'\.(png|jpe?g|gif|svg|webp|ico|css|js|json|woff2?|ttf|eot|pdf|mp3|ogg|webm)$',
    re.IGNORECASE)


def _clean_href(href):
    """Normalise a ZIM-internal href down to a bare title, or None if it
    isn't a same-archive article link (external, anchor, mailto, image...)."""
    if not href or href.startswith('#') or href.startswith('mailto:') \
            or '://' in href or href.startswith('//'):
        return None
    href = href.split('#', 1)[0]
    href = _SKIP_PREFIX.sub('', href)
    href = _NS_PREFIX.sub('', href)
    if not href or _ASSET_EXT.search(href):
        return None
    return unquote(href).replace('_', ' ').strip()


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class _Rewriter(HTMLParser):
    """Streams ZIM article HTML back out, keeping only the actual article
    body (MediaWiki's #mw-content-text container — the ZIM stores the whole
    page, nav chrome and all), rewriting internal <a href> links to the given
    prefix and recording every distinct link target seen.

    If the container id is never found (a differently-built ZIM), falls back
    to emitting everything — a messy page beats a blank one.
    """

    CONTENT_ID = 'mw-content-text'

    # Structural/non-visible tags that must never end up inside our fragment
    # (matters mainly for the only_content=False fallback, since a real
    # #mw-content-text container shouldn't contain these anyway).
    _SKIP_TAGS = {'html', 'head', 'body'}

    def __init__(self, wiki_prefix, only_content=True):
        super().__init__(convert_charrefs=True)
        self.wiki_prefix = wiki_prefix
        self.out = []
        self.links = []
        self.only_content = only_content
        self.capturing = not only_content
        self.depth = 0
        self.found_container = not only_content
        self.drop = 0   # >0 while inside an element whose content must not render at all
        self.raw = 0    # >0 while inside a <style> we're keeping verbatim (real CSS, not HTML)

    def _emit(self, tag, attrs, self_closing):
        if tag in self._SKIP_TAGS:
            return
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            title = _clean_href(attrs['href'])
            if title is not None:
                self.links.append(title)
                attrs['href'] = self.wiki_prefix + title.replace(' ', '_')
        bits = [tag]
        for k, v in attrs.items():
            bits.append(k if v is None else f'{k}="{_esc(v)}"')
        self.out.append('<' + ' '.join(bits) + ('/>' if self_closing else '>'))

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if not self.capturing and not self.found_container and ad.get('id') == self.CONTENT_ID:
            self.capturing = True
            self.found_container = True
            self.depth = 0
            return                              # don't emit the container div itself
        if not self.capturing:
            return
        if tag not in _VOID and self.only_content:
            self.depth += 1
        if tag == 'script' or tag == 'title':
            self.drop += 1
            return                              # never emit these or their content
        if tag == 'style':
            # TemplateStyles blocks are real, scoped CSS for infoboxes,
            # navboxes, hide/show rules etc. — genuinely needed for the page
            # to look right, so keep them verbatim in the normal path. Only
            # drop them in the only_content=False fallback, where a <style>
            # found this way is more likely stray page-chrome CSS anyway.
            if self.only_content:
                self.raw += 1
            else:
                self.drop += 1
        self._emit(tag, ad, self_closing=tag in _VOID)

    def handle_startendtag(self, tag, attrs):
        if self.capturing and tag not in ('script', 'title'):
            self._emit(tag, dict(attrs), self_closing=True)

    def handle_endtag(self, tag):
        if not self.capturing or tag in _VOID:
            return
        if self.only_content:
            self.depth -= 1
            if self.depth < 0:
                self.capturing = False          # closed the container itself
                return
        if tag == 'script' or tag == 'title':
            if self.drop > 0:
                self.drop -= 1
            return
        if tag == 'style':
            if self.only_content:
                if self.raw > 0:
                    self.raw -= 1
            elif self.drop > 0:
                self.drop -= 1
        if tag not in self._SKIP_TAGS:
            self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.capturing or self.drop > 0:
            return
        self.out.append(data if self.raw > 0 else _esc(data))


class ZimContent:
    def __init__(self, path, wiki_prefix='/wiki/'):
        self.archive = Archive(path)
        self.wiki_prefix = wiki_prefix

    def _entry(self, title):
        path = title.replace(' ', '_')
        try:
            entry = self.archive.get_entry_by_path(path)
        except Exception:
            return None
        for _ in range(5):                       # follow ZIM-internal redirects
            if not getattr(entry, 'is_redirect', False):
                break
            try:
                entry = entry.get_redirect_entry()
            except Exception:
                break
        return entry

    def has(self, title):
        return self._entry(title) is not None

    def get(self, title):
        """{'title': canonical slug, 'html': rewritten HTML, 'links': [titles]}
        or None if the title isn't in the archive."""
        entry = self._entry(title)
        if entry is None:
            return None
        try:
            raw = bytes(entry.get_item().content).decode('utf-8', 'replace')
        except Exception:
            return None
        rw = _Rewriter(self.wiki_prefix, only_content=True)
        rw.feed(raw)
        if not rw.found_container:              # unexpected page shape — don't show a blank page
            rw = _Rewriter(self.wiki_prefix, only_content=False)
            rw.feed(raw)
        canon = (entry.title or title).replace(' ', '_')
        heading = f'<h1>{_esc(canon.replace("_", " "))}</h1>'
        return {'title': canon, 'html': heading + ''.join(rw.out), 'links': rw.links}
