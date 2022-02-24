from io import BytesIO
import os
from time import strptime
import aiohttp
import datetime
import calendar
import re
import base64
import json
from hoshino import Service, priv 
from hoshino.util import FreqLimiter
from hoshino.typing import CQEvent
import matplotlib.pyplot as plt
import matplotlib.font_manager as font_manager
from PIL import Image,ImageFont,ImageDraw
import math

from ..pcr_autocb.cbsimple import multigroup, get_start_end_date
if multigroup:
    from ..pcr_autocb.dao_multi import MemberDao, RecordDao
else:
    from ..pcr_autocb.dao import MemberDao, RecordDao


lmt = FreqLimiter(60)   #冷却时间60秒
bg_resign = 'resign.jpg'
bg_report = 'report.jpg'
font_path = os.path.join(os.path.dirname(__file__), 'SimHei.ttf')
constellation_name = ['水瓶', '双鱼', '白羊', '金牛', '双子', '巨蟹', '狮子', '处女', '天秤', '天蝎', '射手', '摩羯']
cycle_data = {
    'cn': {
        'cycle_mode': 'days',
        'cycle_days': 27,
        'base_date': datetime.date(2021, 5, 9),  #从金牛开始计算
        'base_month': 3,
        'battle_days': 6,
        'reserve_days': 0
    },
    'jp': {
        'cycle_mode': 'nature',
        'cycle_days': 0,
        'base_date': None,
        'base_month': 0,
        'battle_days': 5,
        'reserve_days': 1   #月末保留非工会战天数
    },
    'tw': {
        'cycle_mode': 'nature',
        'cycle_days': 0,
        'base_date': None,
        'base_month': 7,
        'battle_days': 5,
        'reserve_days': 1
    }
}
url_valid = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
        r'localhost|' #localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

sv = Service('clanbattle_report', bundle='pcr查询', help_='生成会战报告 [@用户] : 生成会战报告\n生成离职报告 [@用户]: 生成离职报告')


#获取字符串长度（以半角字符计算）
def str_len(name):
    i = 0
    for uchar in name:
        if ord(uchar) > 255:
            i = i + 2
        else:
            i = i + 1
    return i

#获取工会战开始天数 第一天=0
#日服台服开始前返回值为负 国服为正(大于工会战持续天数)
async def get_days_from_battle_start(server='cn'):
    start_date, _ = await get_start_end_date()
    today = datetime.date.today()
    if start_date is None:
        return -1
    else:
        start_date = datetime.date.fromisoformat(start_date)
        diff = today - start_date
        return diff.days
    
#获取工会战总天数
def get_battle_days(server='cn'):
    if not server in cycle_data.keys():
        return 6
    return cycle_data[server]['battle_days']

#获取工会战实际月份
async def get_clanbattle_month(server='cn'):
    if not server in cycle_data.keys():
        return 0
    else:   
        start_date, _ = await get_start_end_date()
        if start_date is None:
            start_date = datetime.date.today() - datetime.timedelta(days=7)
        else:
            start_date = datetime.date.fromisoformat(start_date)
        return (start_date.year, start_date.month, start_date.day)

#获取工会战星座月份
async def get_constellation(server='cn'):
    year, month, day = await get_clanbattle_month()
    start_date = datetime.date(year, month, day)
    return get_constellation_from_date(start_date)

def add_text(img: Image,text:str,textsize:int,font=font_path,textfill='black',position:tuple=(0,0)):
    #textsize 文字大小
    #font 字体，默认微软雅黑
    #textfill 文字颜色，默认黑色
    #position 文字偏移（0,0）位置，图片左上角为起点
    img_font = ImageFont.truetype(font=font,size=textsize)
    draw = ImageDraw.Draw(img)
    draw.text(xy=position,text=text,font=img_font,fill=textfill)
    return img

async def get_data_from_db(qqid, group_id):
    result = {
        'code': 1,
        'msg': '',
        'nickname': '',
        'clanname': ' ',
        'game_server': 'cn',
        'challenge_list': [],
    }
    

    memberDB = MemberDao()
    recordDB = RecordDao()
    nickname = memberDB.get_name_from_qq(qqid, group_id)


    if not nickname:
        result['msg'] = '未找到与该用户绑定的游戏昵称,请先发送[注册+游戏昵称]注册'
        return result

    result['nickname'] = nickname

    year, month, day = await get_clanbattle_month()
    start = datetime.date(year, month, day).strftime('%Y-%m-%d')

    records = recordDB.get_member_monthly_record(nickname, start, group_id)
    if not records:
        result['msg'] = '没有找到你的出刀记录'
        return result

    for item in records:
        challenge = {
            'damage': item['damage'],
            'type': item['flag'], #类型 0 普通 1 尾刀 2 补偿刀
            'boss': item['boss'] - 1,
            'cycle': item['lap'],
        }
        result['challenge_list'].append(challenge)
    result['code'] = 0
    return result

async def send_report(bot, event, background = 0):
    uid = None

    for m in event['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            uid = int(m.data['qq'])
    if uid is None or uid == event['user_id']: #本人
        uid = event['user_id']
    else:   #指定对象
        if not priv.check_priv(event,priv.SUPERUSER):
            await bot.send(event, '查看指定用户的报告需要群主权限')
            return


    if not lmt.check(uid):
        await bot.send(event, f'报告生成器冷却中,剩余时间{round(lmt.left_time(uid))}秒')
        return
    lmt.start_cd(uid)

    result = await get_data_from_db(uid, event.group_id)

    if result['code'] != 0:
        await bot.send(event, result['msg'])
        return
    result['background'] = background
    msg = await generate_report(result)
    await bot.send(event, msg)

async def generate_report(data):
    if data['code'] != 0:
        return data['msg']
    nickname = data['nickname']
    clanname = data['clanname']
    game_server = data['game_server']
    challenge_list = data['challenge_list']
    background = bg_report
    if 'background' in data and data['background'] == 1:
        background = bg_resign
    
    total_challenge = 0 #总出刀数
    total_damage = 0    #总伤害
    lost_challenge = 0  #掉刀
    forget_challenge = 0    #漏刀
    damage_to_boss = [0 for i in range(5)]  #各boss总伤害
    times_to_boss = [0 for i in range(5)]   #各boss出刀数
    truetimes_to_boss = [0 for i in range(5)]   #各boss出刀数 不包括尾刀
    avg_boss_damage = [0 for i in range(5)] #boss均伤
    attendance_rate = 0 #出勤率
    battle_days = get_battle_days(game_server) #会战天数
    #计算当前为工会战第几天 取值范围1~battle_days
    current_days = await get_days_from_battle_start(game_server) 
    if current_days < 0 or current_days >= battle_days:
        current_days = battle_days
    else: #0 ~ battle_days-1
        pass

    i = 0
    while i < len(challenge_list):
        challenge = challenge_list[i]
        times_to_boss[challenge['boss']] += 1
        if challenge['damage'] == 0:    #掉刀
            lost_challenge += 1
        elif challenge['type'] == 0: #普通刀
            damage_to_boss[challenge['boss']] += challenge['damage']  #尾刀伤害不计入单boss总伤害，防止avg异常
            truetimes_to_boss[challenge['boss']] += 1
            total_challenge += 1
        elif challenge['type'] == 1: #尾刀
            if (i + 1) < len(challenge_list) and challenge_list[i+1]['type'] != 0: #下一刀不是普通刀
                next_challenge = challenge_list[i+1]
                if challenge['damage'] > next_challenge['damage']:
                    damage_to_boss[challenge['boss']] += challenge['damage']
                    damage_to_boss[challenge['boss']] += next_challenge['damage']
                    truetimes_to_boss[challenge['boss']] += 1
                else:
                    damage_to_boss[next_challenge['boss']] += challenge['damage']
                    damage_to_boss[next_challenge['boss']] += next_challenge['damage']
                    truetimes_to_boss[next_challenge['boss']] += 1
                i += 1 #跳过下一条数据
            else:
                damage_to_boss[challenge['boss']] += challenge['damage']
                truetimes_to_boss[challenge['boss']] += 1
            total_challenge += 1
        i += 1

    for i in range(len(challenge_list)):
        challenge = challenge_list[i]
        total_damage += challenge['damage']

    if current_days * 3 < total_challenge: #如果会战排期改变 修正天数数据
        current_days =  math.ceil(float(total_challenge) / 3)
    avg_day_damage = int(total_damage/current_days)
    forget_challenge = current_days * 3 - total_challenge
    if forget_challenge < 0:    #修正会战天数临时增加出现的负数漏刀
        forget_challenge = 0
    attendance_rate = round(total_challenge / (current_days * 3) * 100)

    for i in range(0,5):
        if truetimes_to_boss[i] > 0:    #排除没有出刀或只打尾刀的boss
            avg_boss_damage[i] = damage_to_boss[i] // truetimes_to_boss[i]    #尾刀不计入均伤和出刀图表
    
    #设置中文字体
    font_manager.fontManager.addfont(font_path)
    plt.rcParams['font.family']=['SimHei'] #用来正常显示中文标签
    plt.rcParams['axes.unicode_minus']=False #用来正常显示负号

    x = [f'{x}王' for x in range(1,6)]
    y = truetimes_to_boss
    plt.figure(figsize=(4.3,2.8))
    ax = plt.axes()

    #设置标签大小
    plt.tick_params(labelsize=15)

    #设置y轴不显示刻度
    plt.yticks([])

    #绘制刀数柱状图
    recs = ax.bar(x,y,width=0.618,color=['#fd7fb0','#ffeb6b','#7cc6f9','#9999ff','orange'],alpha=0.4)

    #删除边框
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)

    #设置数量显示
    for i in range(0,5):
        rec = recs[i]
        h = rec.get_height()
        plt.text(rec.get_x()+0.1, h, f'{int(truetimes_to_boss[i])}刀',fontdict={"size":12})
    buf = BytesIO()
    plt.savefig(buf, format='png', transparent=True, dpi=120)
    bar_img1 = Image.open(buf)
    #清空图
    plt.clf()

    x = [f'{x}王' for x in range(1,6)]
    y = avg_boss_damage
    plt.figure(figsize=(4.3,2.8))
    ax = plt.axes()

    #设置标签大小
    plt.tick_params(labelsize=15)

    #设置y轴不显示刻度
    plt.yticks([])

    #绘制均伤柱状图
    recs = ax.bar(x,y,width=0.618,color=['#fd7fb0','#ffeb6b','#7cc6f9','#9999ff','orange'],alpha=0.4)

    #删除边框
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)

    #设置数量显示
    for i in range(0,5):
        rec = recs[i]
        h = rec.get_height()
        plt.text(rec.get_x(), h, f'{int(avg_boss_damage[i]/10000)}万',fontdict={"size":12})

    buf = BytesIO()
    plt.savefig(buf, format='png', transparent=True, dpi=120)
    bar_img2 = Image.open(buf)

    #将饼图和柱状图粘贴到模板图,mask参数控制alpha通道，括号的数值对是偏移的坐标
    current_folder = os.path.dirname(__file__)
    img = Image.open(os.path.join(current_folder,background))
    img.paste(bar_img1, (580,950), mask=bar_img1.split()[3])
    img.paste(bar_img2, (130,950), mask=bar_img2.split()[3])

    #添加文字到img
    row1 = f'''
    {total_challenge}

    {forget_challenge}

    {total_damage // 10000}万
    '''
    row2 = f'''
    {attendance_rate}%

    {lost_challenge}

    {avg_day_damage // 10000}万
    '''
    
    add_text(img, row1, position=(380,630), textsize=42)
    add_text(img, row2, position=(833,630), textsize=42)

    year, month, _ = await get_clanbattle_month(game_server)
    add_text(img, str(year), position=(355,445), textsize=40)
    add_text(img, str(month), position=(565,445), textsize=40)
    add_text(img, await get_constellation(game_server), position=(710,445), textsize=40)

    # 公会名称区域 (300,520) (600, 560) width:300 height:40
    # 使用40号字体，最长可放置20个半角字符，如果超长则自动缩减字体并移动坐标
    length = str_len(clanname)
    font_size = 600 // length
    if font_size > 40:
        font_size = 40
    x = 450 - length * font_size // 4
    y = 520 + (40 - font_size) // 2
    add_text(img, clanname, position=(x, y), textsize=font_size) #公会名

    add_text(img, nickname, position=(280,367), textsize=40, textfill='white',)   #角色名
    #输出
    buf = BytesIO()
    img.save(buf,format='JPEG')
    base64_str = f'base64://{base64.b64encode(buf.getvalue()).decode()}'
    msg = f'[CQ:image,file={base64_str}]'
    plt.close('all')
    return msg

@sv.on_prefix('生成离职报告')
async def create_resign_report(bot, event: CQEvent):
    await send_report(bot, event, 1)

@sv.on_prefix('生成会战报告')
async def create_clanbattle_report(bot, event: CQEvent):
    await send_report(bot, event, 0)




def get_constellation_from_date(date:datetime.date):
    month = date.month
    day = date.day
    dates = ((1,20),(2,19),(3,21),(4,21),(5,21),(6,22),(7,23),(8,23),(9,23),(10,23),(11,23),(12,23))
    month_num = -1
    for d in dates:
        if (month, day) <= d:
            return constellation_name[month_num]
        else:
            month_num += 1
    return constellation_name[month_num]