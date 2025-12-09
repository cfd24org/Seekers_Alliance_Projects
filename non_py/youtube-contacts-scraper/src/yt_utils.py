def extract_links_and_emails(text):
    if not text:
        return [], []
    urls = URL_RE.findall(text)
    emails = EMAIL_RE.findall(text)
    emails = [e for e in emails if 'youtube' not in e and 'youtu.be' not in e]
    return list(dict.fromkeys(urls)), list(dict.fromkeys(emails))


def normalize_url(base, href):
    if not href:
        return ''
    href = href.strip()
    if href.startswith('//'):
        return 'https:' + href
    if href.startswith('/'):
        return urljoin(base, href)
    if href.startswith('http'):
        return href
    return urljoin(base, href)


def domain_of(u: str):
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ''


def canonical_video_url(u: str):
    try:
        p = urlparse(u)
        netloc = (p.netloc or '').lower()
        if 'youtu.be' in netloc:
            vid = p.path.lstrip('/')
            if vid:
                return f'https://www.youtube.com/watch?v={vid}'
        from urllib.parse import parse_qs
        qs = parse_qs(p.query)
        v = qs.get('v', [None])[0]
        if v:
            return f'https://www.youtube.com/watch?v={v}'
        scheme = p.scheme or 'https'
        return urljoin(f'{scheme}://{p.netloc}', p.path)
    except Exception:
        return u