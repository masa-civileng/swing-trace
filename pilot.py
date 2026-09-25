"""Small pilot's local quota store. Community Cloud storage is not durable."""
import hashlib, math, sqlite3, tempfile, threading, time, shutil
from pathlib import Path
from contextlib import contextmanager

ROOT=Path(tempfile.gettempdir())/'swing-trace-streamlit-v1'
LOCK=threading.Lock()

def identity(code):return hashlib.sha256(code.encode()).hexdigest()

@contextmanager
def database():
    ROOT.mkdir(exist_ok=True)
    c=sqlite3.connect(ROOT/'quota.sqlite',timeout=10)
    try:
        with c:
            c.execute('CREATE TABLE IF NOT EXISTS quota(day TEXT,owner TEXT,n INTEGER,PRIMARY KEY(day,owner))')
            yield c
    finally:c.close()

def reserve(owner,start,duration,fps,global_limit,user_limit):
    if not math.isfinite(start) or not 0<=start<=600 or not math.isfinite(duration) or not .2<=duration<=6 or fps not in (5,10,30):
        raise ValueError('開始時刻は0～600秒、解析時間は0.2～6秒で指定してください。')
    n=math.ceil(duration*fps)+1
    if n>60:raise ValueError('最大60枚です。解析時間か密度を下げてください。')
    day=time.strftime('%Y-%m-%d',time.gmtime())
    with database() as c:
        c.execute('BEGIN IMMEDIATE')
        total=c.execute('SELECT COALESCE(sum(n),0) FROM quota WHERE day=?',(day,)).fetchone()[0]
        user=c.execute('SELECT n FROM quota WHERE day=? AND owner=?',(day,owner)).fetchone()
        if total+n>global_limit or (user[0] if user else 0)+n>user_limit:
            raise ValueError(f'必要枚数は{n}枚です。本日の残りは、この招待コード{max(0,user_limit-(user[0] if user else 0))}枚、全体{max(0,global_limit-total)}枚です。解析時間か密度を下げてください。')
        c.execute('INSERT INTO quota VALUES(?,?,?) ON CONFLICT(day,owner) DO UPDATE SET n=n+excluded.n',(day,owner,n))
    return n

def cleanup():
    ROOT.mkdir(exist_ok=True)
    for path in ROOT.iterdir():
        if path.is_dir() and len(path.name)==32 and all(c in '0123456789abcdef' for c in path.name) and time.time()-path.stat().st_mtime>86400:
            assert path.resolve().parent==ROOT.resolve()
            shutil.rmtree(path)


def remaining(owner,global_limit,user_limit):
    day=time.strftime('%Y-%m-%d',time.gmtime())
    with database() as c:
        total=c.execute('SELECT COALESCE(sum(n),0) FROM quota WHERE day=?',(day,)).fetchone()[0]
        user=c.execute('SELECT n FROM quota WHERE day=? AND owner=?',(day,owner)).fetchone()
    return max(0,global_limit-total),max(0,user_limit-(user[0] if user else 0))
