#!/usr/bin/env python3
"""clean_yt_contacts.py

Small CLI to clean an extracted YouTube contacts CSV produced by
extract_contacts_from_youtube.py. It removes redundant links that
point back to the original channel (including Google accounts login
redirect wrappers) and drops columns that are empty after cleaning.

Usage:
  python clean_yt_contacts.py --input outputs/yt_contacts.csv --output outputs/yt_contacts_clean.csv

"""
import argparse
import csv
import io
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode, urlunparse
from datetime import datetime

try:
    from python_src.shared import csv_helpers
except Exception:
    import csv_helpers

# simple helper: extract youtube idents from a url (handles, /channel/, /user/)

def _extract_youtube_idents(u: str):
    idents = set()
    if not u:
        return idents
    try:
        parsed = urlparse(u)
        qs = parse_qs(parsed.query)
        # look into common wrapper params
        for key in ('continue', 'q', 'u', 'url'):
            if key in qs:
                for v in qs.get(key, []):
                    try:
                        vv = unquote(v)
                        idents.update(_extract_youtube_idents(vv))
                    except Exception:
                        continue
        # try unwrap redirect style with q param
        if 'youtube.com/redirect' in u:
            q = parse_qs(parsed.query).get('q')
            if q:
                try:
                    idents.update(_extract_youtube_idents(unquote(q[0])))
                except Exception:
                    pass
        # inspect path
        pu = urlparse(u)
        path = (pu.path or '').lower()
        if '/@' in path:
            try:
                after = path.split('/@', 1)[1]
                handle = after.split('/')[0]
                if handle:
                    idents.add(f'@{handle}')
            except Exception:
                pass
        if '/channel/' in path:
            try:
                after = path.split('/channel/', 1)[1]
                cid = after.split('/')[0]
                if cid:
                    idents.add(f'channel:{cid}')
            except Exception:
                pass
        if '/user/' in path:
            try:
                after = path.split('/user/', 1)[1]
                uid = after.split('/')[0]
                if uid:
                    idents.add(f'user:{uid}')
            except Exception:
                pass
        # also record normalized host+path as fallback
        try:
            if pu.scheme and pu.netloc:
                norm = pu._replace(fragment='').geturl().rstrip('/')
                idents.add(norm)
        except Exception:
            pass
    except Exception:
        pass
    return idents


def _normalize_and_unwrap(u: str):
    if not u:
        return u
    u = u.strip()
    # make protocol-relative explicit
    if u.startswith('//'):
        u = 'https:' + u
    # if it's a bare path, leave it
    try:
        p = urlparse(u)
        if p.scheme and p.netloc:
            # for accounts.google continue wrappers we often want the continue target
            if 'accounts.google.com' in p.netloc:
                qs = parse_qs(p.query)
                for key in ('continue', 'q', 'url'):
                    if key in qs:
                        try:
                            return unquote(qs[key][0])
                        except Exception:
                            continue
            # if it's a youtube redirect with q param
            if 'youtube.com' in p.netloc and p.path.startswith('/redirect'):
                q = parse_qs(p.query).get('q')
                if q:
                    try:
                        return unquote(q[0])
                    except Exception:
                        pass
            return p._replace(fragment='').geturl()
    except Exception:
        pass
    return u


def _canonicalize_email_addr(e: str) -> str:
    """Normalize an email address: strip mailto:, lowercase, remove surrounding <> and whitespace."""
    if not e:
        return e
    s = e.strip()
    if s.lower().startswith('mailto:'):
        s = s.split(':', 1)[1]
    # remove common wrapping characters
    s = s.strip().strip('<>').strip()
    return s.lower()


TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'fbclid', 'gclid',
    'mc_cid', 'mc_eid', 'ref', 'ref_src', 'igshid'
}

# Keep some youtube params that are meaningful
YOUTUBE_KEEP_PARAMS = {'v', 'list', 't', 'index'}


def _canonicalize_url(u: str) -> str:
    """Normalize URLs:
    - ensure scheme https
    - lowercase netloc and remove leading www.
    - drop tracking params
    - preserve meaningful params for youtube (e.g. v, list)
    - remove fragments
    - strip trailing slash (unless only path '/')
    """
    if not u:
        return u
    try:
        u = u.strip()
        # already unwrapped by _normalize_and_unwrap in most cases
        parsed = urlparse(u)
        # if no scheme but starts with www, add https
        scheme = parsed.scheme or 'https'
        netloc = (parsed.netloc or parsed.path).lower()
        # If netloc was empty then parsed.path may contain host when scheme missing
        if ':' in netloc and netloc.count(':') == 1 and netloc.startswith('http'):
            # fallback: parse again
            parsed = urlparse('https://' + u)
            scheme = parsed.scheme
            netloc = parsed.netloc.lower()
        # normalize netloc
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        # parse query and drop tracking params
        qs = parse_qs(parsed.query)
        new_qs = {}
        for k, vals in qs.items():
            if k in TRACKING_PARAMS:
                continue
            # keep youtube-essential params
            if 'youtube.com' in netloc or 'youtu.be' in netloc:
                if k in YOUTUBE_KEEP_PARAMS:
                    new_qs[k] = vals
                else:
                    # drop other params often used for tracking / redirects
                    continue
            else:
                new_qs[k] = vals
        new_query = urlencode(new_qs, doseq=True) if new_qs else ''
        path = parsed.path or ''
        # remove duplicate slashes and trailing slash
        if path.endswith('/') and path != '/':
            path = path.rstrip('/')
        rebuilt = urlunparse((scheme, netloc, path, '', new_query, ''))
        return rebuilt
    except Exception:
        return u.strip()


def read_csv_skip_comments(path):
    with open(path, 'r', encoding='utf-8', newline='') as fh:
        raw = fh.read().splitlines()
    start = 0
    for i, ln in enumerate(raw):
        if ln.strip() == '' or ln.lstrip().startswith('#'):
            continue
        start = i
        break
    cleaned = raw[start:]
    if not cleaned:
        raise SystemExit('No CSV content after skipping comments')
    reader = csv.DictReader(io.StringIO('\n'.join(cleaned)))
    rows = list(reader)
    return reader.fieldnames, rows


def write_with_author_note(path, fieldnames, rows):
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        try:
            fh.write(f"# created_by: clean_yt_contacts.py | {datetime.utcnow().isoformat()}Z\n")
        except Exception:
            pass
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    try:
        csv_helpers.prepend_author_note(path, created_by='clean_yt_contacts.py')
    except Exception:
        pass


def clean_row_links(row, channel_col_names=('channel_url', 'channel')):
    # find channel url for this row
    channel_url = ''
    for c in channel_col_names:
        if row.get(c):
            channel_url = row.get(c)
            break
    channel_idents = _extract_youtube_idents(channel_url) if channel_url else set()

    cleaned_row = dict(row)
    # iterate over every column cell and clean any http/mailto lists (pipe-separated)
    for col, val in list(row.items()):
        if not isinstance(val, str) or not val:
            cleaned_row[col] = val
            continue
        # heuristic: only process cells that look like containing urls (http, www, mailto)
        if ('http' not in val) and ('mailto' not in val) and ('www.' not in val):
            cleaned_row[col] = val
            continue
        parts = [p.strip() for p in val.split('|') if p.strip()]
        new_parts = []
        seen = set()
        for p in parts:
            np = _normalize_and_unwrap(p)
            # skip empty
            if not np:
                continue
            # if np is a wrapper back to accounts.google with a continue to the same channel -> drop
            try:
                parsed = urlparse(np)
                if 'accounts.google.com' in parsed.netloc:
                    qs = parse_qs(parsed.query)
                    for key in ('continue', 'q', 'url'):
                        if key in qs:
                            try:
                                cont = unquote(qs[key][0])
                                cont_idents = _extract_youtube_idents(cont)
                                if channel_idents and (cont_idents & channel_idents):
                                    np = None
                                    break
                            except Exception:
                                continue
                # Also drop youtube signin/redirect wrappers like /signin?next=/@Handle or with continue/q/url
                if np:
                    try:
                        if 'youtube.com' in parsed.netloc and parsed.path.startswith('/signin'):
                            qs2 = parse_qs(parsed.query)
                            for key in ('next', 'continue', 'q', 'url'):
                                if key in qs2:
                                    try:
                                        val = unquote(qs2[key][0])
                                        # make absolute if it's a path-only value
                                        if val.startswith('/'):
                                            val_full = urljoin('https://www.youtube.com', val)
                                        else:
                                            val_full = val
                                        cont_idents = _extract_youtube_idents(val_full)
                                        if channel_idents and (cont_idents & channel_idents):
                                            np = None
                                            break
                                    except Exception:
                                        continue
                    except Exception:
                        pass
                if not np:
                    continue
            except Exception:
                pass
            # if np directly identifies same channel via handle/channel/user -> drop
            try:
                cand_idents = _extract_youtube_idents(np)
                if channel_idents and (cand_idents & channel_idents):
                    continue
            except Exception:
                pass

            # canonicalize mailto vs http urls
            try:
                if np.lower().startswith('mailto:'):
                    ce = _canonicalize_email_addr(np)
                    if ce and ce not in seen:
                        seen.add(ce)
                        new_parts.append(ce)
                    continue
                else:
                    cu = _canonicalize_url(np)
                    if cu and cu not in seen:
                        seen.add(cu)
                        new_parts.append(cu)
            except Exception:
                # fallback to raw normalized/unwrapped value
                if np not in seen:
                    seen.add(np)
                    new_parts.append(np)

        cleaned_row[col] = '|'.join(new_parts)
    return cleaned_row


def drop_empty_columns(fieldnames, rows):
    keep = []
    for col in fieldnames:
        nonempty = any((r.get(col) or '').strip() for r in rows)
        if nonempty:
            keep.append(col)
    return keep


def main():
    parser = argparse.ArgumentParser(description='Clean extracted YouTube contacts CSV')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    fieldnames, rows = read_csv_skip_comments(args.input)
    cleaned_rows = []
    for r in rows:
        cleaned_rows.append(clean_row_links(r))

    # drop columns that are empty across all rows
    keep_cols = drop_empty_columns(fieldnames, cleaned_rows)

    # reorder/trim rows to include only keep_cols
    out_rows = []
    for r in cleaned_rows:
        out_rows.append({k: r.get(k, '') for k in keep_cols})

    if args.dry_run:
        print(f"Would write {len(out_rows)} rows and {len(keep_cols)} columns to {args.output}")
        return

    write_with_author_note(args.output, keep_cols, out_rows)
    print(f'Wrote cleaned CSV to {args.output} ({len(out_rows)} rows, {len(keep_cols)} cols)')


if __name__ == '__main__':
    main()
