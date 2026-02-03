#!/usr/bin/env python3
"""
uniformize_links.py

Normalize extracted links and collapse duplicates by canonical identity.
Produces a CSV with columns for canonical form and service classification.

Usage:
  python uniformize_links.py --input extracted_links.csv --output uniform_links.csv

"""
import argparse
import csv
from urllib.parse import urlparse, parse_qs, unquote


def canonicalize_youtube(u):
    # handle google accounts continuations and /@ handles and /channel/ ids
    try:
        if 'accounts.google.com' in u:
            parsed = urlparse(u)
            q = parse_qs(parsed.query)
            cont = q.get('continue') or q.get('next') or q.get('q')
            if cont:
                cand = unquote(cont[0])
                u = cand
        p = urlparse(u)
        net = p.netloc.lower().replace('www.', '')
        path = p.path.rstrip('/')
        # handle handles like /@handle -> canonicalize to @handle
        if net.endswith('youtube.com'):
            if path.startswith('/@'):
                return f'youtube:@{path.split('/@')[-1]}'
            if path.startswith('/channel/'):
                return f'youtube:channel:{path.split('/')[-1]}'
            # sometimes path is /c/Name or /user/Name
            if path.startswith('/c/') or path.startswith('/user/'):
                return f'youtube:custom:{path.split('/')[-1]}'
        return None
    except Exception:
        return None


def canonical(u):
    if not u:
        return None, None
    u = u.strip()
    # unify schemes
    if u.startswith('http://'):
        u = 'https://' + u[len('http://'):]
    # remove trailing query fragments for identity unless they carry meaningful info
    p = urlparse(u)
    # google accounts YouTube continuations handled in youtube specific
    y = canonicalize_youtube(u)
    if y:
        return y, 'youtube'
    # other socials: simple netloc-based classification
    net = p.netloc.lower().replace('www.', '')
    if 'twitch.tv' in net:
        # path may be /user or /channel
        path = p.path.rstrip('/')
        return f'twitch:{path.lstrip("/")}', 'twitch'
    if 'twitter.com' in net or 'x.com' in net:
        path = p.path.rstrip('/')
        name = path.lstrip('/')
        return f'twitter:{name}', 'twitter'
    if 'bsky.app' in net or 'bsky.social' in net:
        return f'bluesky:{p.path.rstrip("/")}', 'bluesky'
    # mailto
    if u.lower().startswith('mailto:'):
        return f'email:{u.split(":",1)[1]}', 'email'
    # fallback: normalized full URL without tracking query params
    # remove common tracking query params
    qs = parse_qs(p.query)
    keep_q = {k: v for k, v in qs.items() if k.lower() not in ('utm_source','utm_medium','utm_campaign','utm_term','utm_content','fbclid')}
    base = f'{p.scheme}://{p.netloc}{p.path}'.rstrip('/')
    if keep_q:
        # append normalized query
        qparts = []
        for k in sorted(keep_q.keys()):
            for val in keep_q[k]:
                qparts.append(f'{k}={val}')
        base = base + '?' + '&'.join(qparts)
    # classify common domains
    if 'discord.gg' in net or 'discord.com' in net:
        return f'discord:{base}', 'discord'
    if 'instagram.com' in net:
        return f'instagram:{p.path.rstrip("/")}', 'instagram'
    if 'patreon.com' in net:
        return f'patreon:{p.path.rstrip("/")}', 'patreon'
    if 'linkedin.com' in net:
        return f'linkedin:{p.path.rstrip("/")}', 'linkedin'
    # default website
    return base, 'website'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()

    rows = []
    with open(args.input, 'r', encoding='utf-8', newline='') as fh:
        rdr = csv.DictReader(fh)
        rows = list(rdr)

    seen = {}
    out = []
    for r in rows:
        link = r.get('extracted_link') or r.get('link') or ''
        canon, svc = canonical(link)
        if not canon:
            continue
        key = (svc, canon)
        if key in seen:
            seen[key]['sources'].append(r.get('row_index'))
        else:
            seen[key] = {'canonical': canon, 'service': svc, 'examples': [link], 'sources': [r.get('row_index')]}

    for k, v in seen.items():
        out.append({'service': v['service'], 'canonical': v['canonical'], 'examples': '|'.join(v['examples']), 'sources': '|'.join([str(x) for x in v['sources']])})

    with open(args.output, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['service', 'canonical', 'examples', 'sources'])
        writer.writeheader()
        writer.writerows(out)

    print(f'Wrote {args.output} ({len(out)} canonical links)')

if __name__ == '__main__':
    main()
