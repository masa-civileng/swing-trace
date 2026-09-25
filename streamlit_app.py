"""Invitation-only Streamlit pilot. No credentials or videos belong in this repository."""
import copy, hmac, json, math, os, uuid
from pathlib import Path
import streamlit as st
from PIL import Image, ImageDraw
import media, pilot, vision

st.set_page_config(page_title='SWING TRACE',page_icon='⚾',layout='wide')
st.title('SWING TRACE')
st.caption('バット先端と手元をつなぎ、スイングを面で見る。招待制の試験版です。')

try:
    settings=dict(st.secrets)
except st.errors.StreamlitSecretNotFoundError:
    settings={}
codes=settings.get('ACCESS_CODES',[])
if not isinstance(codes,list) or not codes or any(not isinstance(c,str) or len(c)<20 or c.startswith('REPLACE_') for c in codes):
    st.info('管理者の初期設定待ちです。StreamlitのSecretsにAPIキーと20文字以上の招待コードを設定してください。')
    st.stop()
if not settings.get('OPENAI_API_KEY') or settings['OPENAI_API_KEY'].startswith('REPLACE_'):
    st.info('管理者のAPIキー設定待ちです。');st.stop()
owners=[pilot.identity(c) for c in codes]
if st.session_state.get('owner') not in owners:
    with st.form('login'):
        token=st.text_input('招待コード',type='password')
        login=st.form_submit_button('ログイン')
    if login:
        match=next((c for c in codes if hmac.compare_digest(token.strip(),c)),None)
        if match:
            st.session_state.owner=pilot.identity(match);st.rerun()
        st.error('招待コードを確認してください。')
    st.stop()
os.environ['OPENAI_API_KEY']=settings['OPENAI_API_KEY']
os.environ['OPENAI_MODEL']=settings.get('OPENAI_MODEL','gpt-6-astra')
if os.name!='nt':os.environ['FFMPEG_EXE']='/usr/bin/ffmpeg'
st.sidebar.write('モデル：'+os.environ['OPENAI_MODEL'])
if st.sidebar.button('ログアウト'):
    st.session_state.clear();st.rerun()
st.sidebar.caption('同時解析は1件。途中でブラウザーを閉じずにお待ちください。再起動で結果・利用回数が失われる場合があります。')

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')

def job_folder(job):
    if job['owner']!=st.session_state.owner:raise ValueError('利用者が一致しません。')
    path=pilot.ROOT/job['id'];assert path.resolve().parent==pilot.ROOT.resolve()
    return path

st.subheader('1. 動画と解析区間')
upload=st.file_uploader('MP4 / MOV / WebM（100MB以下）',type=['mp4','mov','webm'],max_upload_size=100)
preview_width=st.select_slider('プレビューの横幅（px）',options=[240,320,400,480,640],value=320)
if upload:st.video(upload,width=preview_width)
a,b,c=st.columns(3)
start=a.number_input('開始時刻（秒）',min_value=0.,max_value=600.,value=0.,step=.1)
duration=b.number_input('解析する長さ（秒）',min_value=.2,max_value=6.,value=1.,step=.1)
fps=c.selectbox('解析密度（毎秒の枚数）',[5,10,30])
st.caption(f'受付時に予約する枚数：{math.ceil(duration*fps)+1}枚。まずは1秒・毎秒5枚で試してください。')
remaining=pilot.remaining(st.session_state.owner,int(settings.get('GLOBAL_DAILY_FRAMES',60)),int(settings.get('USER_DAILY_FRAMES',20)))
st.caption(f'本日の残り：この招待コード {remaining[1]}枚 ／ 全体 {remaining[0]}枚（日本時間9時に日付更新）。')
if math.ceil(duration*fps)+1>min(remaining):
    st.warning('必要枚数が本日の残りを超えています。解析する長さ、または解析密度を下げてください。')
consent=st.checkbox('動画をサーバーへ送信し、選択区間の画像をOpenAIへ送ることに同意します。送信してよい動画を選びました。')
st.caption('選択区間を30fpsに変換して解析します。保存データは次の解析開始時に24時間を超えたものを削除します。クラウド再起動で早く消える場合があります。')
if st.button('この区間を解析する',type='primary'):
    if not upload:st.error('動画を選択してください。')
    elif not consent:st.error('送信への同意を確認してください。')
    elif upload.size>100*1024*1024:st.error('100MB以下の動画を選んでください。')
    elif not pilot.LOCK.acquire(blocking=False):st.warning('別の解析・動画出力を処理中です。少し待ってからお試しください。')
    else:
        job=None
        try:
            pilot.cleanup()
            reserved=pilot.reserve(st.session_state.owner,start,duration,fps,int(settings.get('GLOBAL_DAILY_FRAMES',60)),int(settings.get('USER_DAILY_FRAMES',20)))
            job={'id':uuid.uuid4().hex,'owner':st.session_state.owner,'status':'running','points':[],'revision':0}
            st.session_state.job=job;p=job_folder(job);p.mkdir();(p/'upload.bin').write_bytes(upload.getbuffer())
            with st.status('動画を準備しています…',expanded=True) as status:
                meta=media.prepare(p,start,duration,30//fps);job['meta']=meta
                if len(meta['samples'])>reserved:raise ValueError('予定した解析枚数を超えました。')
                progress=st.progress(0);text=st.empty();(p/'api').mkdir()
                for k,frame in enumerate(meta['samples']):
                    text.write(f'AI解析中：{k+1} / {len(meta["samples"])}枚目。画像によって数十秒以上かかります。')
                    result=vision.locate(p/'frames'/f'{frame:05d}.png',meta['width'],meta['height'])
                    save(p/'api'/f'{frame:05d}.json',result)
                    job['points'].append({'frame':frame,**result['points'],'break_before':False})
                    save(p/'points.json',job['points']);progress.progress((k+1)/len(meta['samples']))
                job['status']='review';status.update(label='解析完了。下の画像を確認してください。',state='complete')
        except (ValueError,vision.AnalysisError) as exc:
            if job:job['status']='failed'
            st.error(str(exc))
        except Exception:
            if job:job['status']='failed'
            st.error('処理を完了できませんでした。自動でAPIを再送していません。')
        finally:
            if job and job['status']=='running':job['status']='failed'
            pilot.LOCK.release()

job=st.session_state.get('job')
if not job:st.stop()
p=job_folder(job)
if not p.exists():st.warning('保存期間またはサーバー再起動で結果が失われました。');st.stop()
if job['status']=='failed':st.warning('途中で停止しました。下に取得済み画像があれば確認できます。再解析は別のAPIリクエストになります。')
if not job.get('points'):st.stop()
st.subheader('2. 位置を確認・修正する')
st.caption('赤：先端 ／ 水色：両手の握りの中心 ／ 黄色：通過面。表示コマの間は線形補間しています。')
meta=job['meta'];rows=job['points'];idx=st.select_slider('確認するコマ',options=list(range(len(rows))),format_func=lambda k:f'{k+1}枚目 / 元動画 {meta["start"]+rows[k]["frame"]/30:.3f}秒',key='frame_'+job['id'])
row=rows[idx];im=Image.open(p/'frames'/f'{row["frame"]:05d}.png').convert('RGBA')
fill=Image.new('RGBA',im.size);fd=ImageDraw.Draw(fill);paths=[]
for a,b,pa,pb in media.segments(rows[:idx+1],math.hypot(meta['width'],meta['height'])*.2,meta['step']+1):
    fd.polygon([pa[0],pb[0],pb[1],pa[1]],fill=(248,220,105,50));paths.append((pa,pb))
im=Image.alpha_composite(im,fill);d=ImageDraw.Draw(im)
for pa,pb in paths:
    for k,col in enumerate(['#ff5055','#20d7ee']):d.line([pa[k],pb[k]],fill=col,width=3)
    d.line(pb,fill='#dccc83',width=1)
pts=[media.point(row,k) for k in ('tip','hands')]
if all(pt is not None for pt in pts):d.line(pts,fill='#ffe987',width=3)
for pt,col in zip(pts,['#ff5055','#20d7ee']):
    if pt:
        x,y=pt;d.ellipse((x-8,y-8,x+8,y+8),outline=col,width=3)
left,right=st.columns([2,1]);left.image(im.convert('RGB'),width=preview_width)
with right:
    st.write('座標を数値で修正できます。左上が(0,0)です。')
    with st.form(f'edit_{job["id"]}_{idx}_{job["revision"]}'):
        edit=copy.deepcopy(row)
        for name,label in [('tip','先端'),('hands','手元')]:
            missing=st.checkbox(label+'が見えない',value=row[name]['x'] is None)
            x=st.number_input(label+' X',min_value=0.,max_value=float(meta['width']-1),value=float(row[name]['x'] or 0),step=1.)
            y=st.number_input(label+' Y',min_value=0.,max_value=float(meta['height']-1),value=float(row[name]['y'] or 0),step=1.)
            edit[name]={'x':None if missing else x,'y':None if missing else y,'status':'uncertain' if missing else 'visible','reason':'確認時の指定'}
        edit['break_before']=st.checkbox('このコマの直前で面を切る',value=row.get('break_before',False))
        if st.form_submit_button('このコマの修正を保存'):
            rows[idx]=edit;job['revision']+=1;(p/'output.mp4').unlink(missing_ok=True);save(p/'points.json',rows);st.rerun()
    st.caption('画像をクリックしての修正は、このStreamlit初版には含まれません。')

st.subheader('3. MP4を保存する')
reviewed=st.checkbox('位置と面のつながりを確認しました',key=f'reviewed_{job["id"]}_{job["revision"]}')
if st.button('面付きMP4を作成',disabled=job['status']!='review'):
    if not reviewed:st.error('確認済みにチェックしてください。')
    elif not pilot.LOCK.acquire(blocking=False):st.warning('別の処理が実行中です。しばらく待ってください。')
    else:
        try:
            with st.spinner('MP4を作成しています…'):media.render(p,meta,rows)
        except Exception:st.error('MP4を作成できませんでした。')
        finally:pilot.LOCK.release()
if (p/'output.mp4').exists():
    st.video(str(p/'output.mp4'),width=preview_width)
    st.download_button('MP4をダウンロード',(p/'output.mp4').read_bytes(),file_name='swing-surface.mp4',mime='video/mp4')
st.caption('出力は選択区間のみ・30fps・無音。2Dの推定表示です。速度測定・3D復元ではありません。')
