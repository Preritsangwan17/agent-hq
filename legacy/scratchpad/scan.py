import json, re, sys, urllib.request, concurrent.futures as cf
slugs = sys.argv[1].split(',')
KW = re.compile(r'intern|trainee|apprentice|research assistant|student|co-?op|fellow', re.I)
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=20) as r:
            return json.load(r)
    except Exception as e:
        return None
def scan(slug):
    out=[]
    d=get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs')
    if d and 'jobs' in d:
        for j in d['jobs']:
            if KW.search(j['title']): out.append(('GH',slug,j['title'],j.get('location',{}).get('name',''),j['absolute_url'],j.get('updated_at','')[:10]))
    d=get(f'https://api.lever.co/v0/postings/{slug}?mode=json')
    if isinstance(d,list):
        for j in d:
            if KW.search(j['text']): out.append(('LV',slug,j['text'],j.get('categories',{}).get('location',''),j['hostedUrl'],''))
    d=get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}')
    if d and 'jobs' in d:
        for j in d['jobs']:
            if KW.search(j['title']): out.append(('AB',slug,j['title'],j.get('location',''),j['jobUrl'],j.get('publishedAt','')[:10]))
    return slug, out
with cf.ThreadPoolExecutor(24) as ex:
    for slug,out in ex.map(scan, slugs):
        for o in out: print(' | '.join(o))
