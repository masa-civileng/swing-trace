"""Server-only image localization. Never include this module or a key in the browser."""
import base64, json, os, urllib.request, urllib.error

class AnalysisError(Exception):
    pass

POINT = {'type':'object','properties':{'x':{'type':['number','null']},'y':{'type':['number','null']},'status':{'type':'string','enum':['visible','blurred','occluded','outside_frame','uncertain']},'reason':{'type':'string'}},'required':['x','y','status','reason'],'additionalProperties':False}
SCHEMA = {'type':'object','properties':{'tip':POINT,'hands':POINT},'required':['tip','hands'],'additionalProperties':False}

def locate(path, width, height):
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise AnalysisError('管理者のAPIキーが未設定です。')
    prompt = f'''Locate landmarks of the foreground batter holding the bat in this {width}x{height} image.
tip: center of the distal barrel end cap farthest from the hands, NOT the knob, ball, tee, or a background object.
hands: center of the combined two-hand grip on the bat, NOT the wrists alone.
Return pixel coordinates in this image, origin top left, x right, y down.
Only visible or defensibly localizable blurred landmarks receive coordinates.
For occluded, outside_frame or uncertain landmarks, return null for BOTH x and y; never invent a hidden position.
Describe the reason briefly in Japanese. Interpret this image independently.'''
    body = {'model':os.environ.get('OPENAI_MODEL','gpt-6-astra'),'store':False,
            'reasoning':{'effort':'high'},'max_output_tokens':4096,
            'input':[{'role':'user','content':[{'type':'input_text','text':prompt},{'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode(),'detail':'original'}]}],
            'text':{'format':{'type':'json_schema','name':'swing_landmarks','strict':True,'schema':SCHEMA}}}
    req = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(body).encode(),
                                 headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = json.load(response)
    except urllib.error.HTTPError as exc:
        messages = {401:'APIの認証に失敗しました。',403:'APIへのアクセスが許可されていません。',404:'指定モデルを利用できません。',429:'APIの利用上限に達しました。'}
        raise AnalysisError(messages.get(exc.code,'APIからエラーが返りました。')+' 管理者にご連絡ください。') from None
    except (urllib.error.URLError, TimeoutError):
        raise AnalysisError('API通信が完了しませんでした。二重課金を避けるため自動再送していません。') from None
    if raw.get('status') != 'completed':
        raise AnalysisError('API応答が完了しませんでした。自動再送していません。')
    try:
        text = ''.join(c['text'] for item in raw.get('output',[]) if item.get('type')=='message'
                       for c in item.get('content',[]) if c.get('type')=='output_text')
        points = json.loads(text)
        for name in ('tip','hands'):
            point = points[name]
            x,y = point['x'],point['y']
            if point['status'] in ('visible','blurred'):
                if not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or not 0<=x<width or not 0<=y<height:
                    raise ValueError()
            elif x is not None or y is not None:
                raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise AnalysisError('API座標の形式を確認できませんでした。') from None
    # Store only the structured answer and accounting metadata, never the request/key.
    return {'points':points,'usage':raw.get('usage',{}),'model':raw.get('model'), 'response_id':raw.get('id')}
