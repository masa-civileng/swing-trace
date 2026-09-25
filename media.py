"""Normalized 30fps video, review frames, and a 2D swept surface overlay."""
import json, math, os, subprocess
from pathlib import Path
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
from vision import AnalysisError

FPS = 30

def ffmpeg():
    return os.environ.get('FFMPEG_EXE') or imageio_ffmpeg.get_ffmpeg_exe()

def command(args):
    try:
        subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-nostdin',*args],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=180)
    except (subprocess.SubprocessError, OSError):
        raise AnalysisError('動画を変換できません。短いMP4またはMOVでお試しください。') from None

def prepare(folder, start, duration, step):
    frames = folder/'frames'; frames.mkdir(exist_ok=True)
    # Decode only a selected interval, auto-rotate, preserve aspect ratio; output CFR timestamps.
    vf = "fps=30,scale=w='min(720,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1"
    command(['-y','-ss',str(start),'-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,avi','-i',str(folder/'upload.bin'),
             '-t',str(duration),'-vf',vf,'-an','-c:v','libx264','-preset','fast','-crf','20',str(folder/'clip.mp4')])
    reader=imageio_ffmpeg.read_frames(str(folder/'clip.mp4'),pix_fmt='rgb24')
    meta=next(reader);w,h=meta['size'];count=0
    try:
        for data in reader:
            if count%step==0:
                Image.frombytes('RGB',(w,h),data).save(frames/f'{count:05d}.png')
            count+=1
    finally:reader.close()
    if count<2:raise AnalysisError('選択区間に十分な映像がありません。開始時刻を確認してください。')
    # Include final endpoint so a reviewed interval has an explicit end.
    if not (frames/f'{count-1:05d}.png').exists():
        command(['-y','-i',str(folder/'clip.mp4'),'-vf',f'select=eq(n\\,{count-1})','-frames:v','1',str(frames/f'{count-1:05d}.png')])
    return {'width':w,'height':h,'frames':count,'fps':FPS,'step':step,'start':start,
            'samples':[int(p.stem) for p in sorted(frames.glob('*.png'))]}

def point(row, target):
    p=row.get(target)
    return None if not p or p.get('x') is None else (p['x'],p['y'])

def segments(rows, threshold, max_gap):
    """Never bridge missing landmarks, explicitly broken sections or large jumps."""
    for a,b in zip(rows,rows[1:]):
        if b['frame']-a['frame']>max_gap or b.get('break_before'):continue
        pa=[point(a,k) for k in ('tip','hands')];pb=[point(b,k) for k in ('tip','hands')]
        if all(p is not None for p in pa+pb) and all(math.dist(p,q)<=threshold for p,q in zip(pa,pb)):
            yield a,b,pa,pb

def font(size):
    for path in [os.environ.get('FONT_PATH',''),'C:/Windows/Fonts/meiryo.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
        if path and Path(path).exists():return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)

def render(folder, meta, rows):
    width,height=meta['width'],meta['height'];threshold=math.hypot(width,height)*.2
    valid=list(segments(rows,threshold,meta['step']+1));by_frame={r['frame']:r for r in rows}
    path_layer=Image.new('RGBA',(width,height),(0,0,0,0));fill_layer=path_layer.copy()
    draw_path=ImageDraw.Draw(path_layer);draw_fill=ImageDraw.Draw(fill_layer)
    reader=imageio_ffmpeg.read_frames(str(folder/'clip.mp4'),pix_fmt='rgb24');next(reader)
    writer=imageio_ffmpeg.write_frames(str(folder/'output.part.mp4'),(width,height+120),fps=FPS,
            codec='libx264',pix_fmt_in='rgb24',pix_fmt_out='yuv420p',macro_block_size=2,
            output_params=['-crf','20','-movflags','+faststart'])
    writer.send(None);f=font(16);title_font=font(20);count=0
    try:
        for index,data in enumerate(reader):
            current=[]
            for a,b,pa,pb in valid:
                if not a['frame']<index<=b['frame']:continue
                t=(index-a['frame'])/(b['frame']-a['frame']);prev_t=(index-1-a['frame'])/(b['frame']-a['frame'])
                old=[tuple(p[k]+(q[k]-p[k])*prev_t for k in (0,1)) for p,q in zip(pa,pb)]
                new=[tuple(p[k]+(q[k]-p[k])*t for k in (0,1)) for p,q in zip(pa,pb)]
                # Constant alpha union prevents dense segments becoming opaque.
                draw_fill.polygon([old[0],new[0],new[1],old[1]],fill=(248,220,105,50))
                for j,color in enumerate(['#ff5055','#20d7ee']):draw_path.line([old[j],new[j]],fill=color,width=3)
                if index==b['frame']:draw_path.line(new,fill=(255,232,140,125),width=1)
                current=new
            im=Image.frombytes('RGB',(width,height),data).convert('RGBA')
            im=Image.alpha_composite(Image.alpha_composite(im,fill_layer),path_layer)
            d=ImageDraw.Draw(im)
            if index in by_frame:
                current=[point(by_frame[index],k) for k in ('tip','hands')]
            if current:
                if all(p is not None for p in current):d.line(current,fill='#ffe987',width=3)
                for p,color in zip(current,['#ff5055','#20d7ee']):
                    if p is not None:
                        x,y=p;d.ellipse((x-6,y-6,x+6,y+6),outline=color,width=3)
            out=Image.new('RGB',(width,height+120),'#102238');out.paste(im.convert('RGB'),(0,50));d=ImageDraw.Draw(out)
            d.text((12,10),'SWING TRACE | スイング面',font=title_font,fill='white')
            d.text((12,height+56),f"元動画 {meta['start']+index/FPS:.3f}s / 赤:先端  水色:手元",font=f,fill='white')
            d.text((12,height+83),'2D推定・コマ間補間あり / 欠測・大きな飛びは接続なし',font=f,fill='#f5d77e')
            writer.send(out.tobytes());count+=1
    finally:
        reader.close();writer.close()
    if count!=meta['frames']:raise AnalysisError('書き出したコマ数が一致しません。')
    (folder/'output.part.mp4').replace(folder/'output.mp4')
