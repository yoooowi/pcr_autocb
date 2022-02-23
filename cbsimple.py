import os
import json
import hoshino
import aiohttp
import traceback
from hoshino import HoshinoBot, Service, util, priv, MessageSegment
from .data import *
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps

sv = Service('auto_clanbattle', enable_on_default=True, visible=True)

slDao = SLDao()
subDao = SubscribeDao()
send_long_msg_as_pic = True
#群组
group_ids = []
#挂树
on_tree = {}

#API
MEMBER_API = "https://www.bigfun.cn/api/feweb?target=gzlj-clan-day-report/a&size=30"
BOSS_API = "https://www.bigfun.cn/api/feweb?target=gzlj-clan-day-report-collect/a"
LIST_API = "https://www.bigfun.cn/api/feweb?target=gzlj-clan-boss-report-collect/a"

#载入群设置
def load_group_config(group_id: str) -> int:
    group_id = str(group_id)
    filename = os.path.join(os.path.dirname(__file__), 'config', f'{group_id}.json')
    try:
        with open(filename, encoding='utf8') as f:
            config = json.load(f)
            return config
    except Exception as e:
        hoshino.logger.exception(e)
        return {}

#载入群组


def cookie(group_id):
    return load_group_config(group_id)["cookie"]

def groupids():
    group_ids = util.load_config(__file__)['groupids']
    return group_ids

def get_boss_info():
    boss_name = util.load_config(__file__)['boss_name'] 
    return boss_name

def number_formatter(number: int):
    if number < 10000:
        return str(number)

    number = number/10000
    return f'{number:.0f}万'

async def get_today_data(date: str = None,group_id = None):
    api = MEMBER_API if not date else f'{MEMBER_API}&date={date}'
    try:
        async with aiohttp.ClientSession(cookies=cookie(group_id)) as session:
            async with session.get(api) as resp:
                return await resp.json(content_type='application/json')
    except:
        traceback.print_exc()
    return None

async def get_collect(group_id):
    try:
        async with aiohttp.ClientSession(cookies=cookie(group_id)) as session:
            async with session.get(BOSS_API) as resp:
                return await resp.json(content_type='application/json')
    except:
        traceback.print_exc()
    return None

async def get_boss_list(group_id):
    try:
        async with aiohttp.ClientSession(cookies=cookie(group_id)) as session:
            async with session.get(LIST_API) as resp:
                return await resp.json(content_type='application/json')
    except:
        traceback.print_exc()
    return None

async def get_start_end_date(group_id):
    data = await get_collect(group_id)
    if not data or len(data) == 0:
        sv.logger.error('API访问失败@get_start_end_date')
        return (None, None)
    elif 'data' not in data or len(data['data']) == 0:
        sv.logger.error(f'API数据异常\n{data}@get_start_end_date')
        return (None, None)
    else:
        data = data['data']
        start_date = data['day_list'][-1]
        end_date = data['day_list'][0]
        return (start_date, end_date)


async def update_boss(boss, lap_num, group_id, send_msg=False):
    curr_boss = subDao.curr_boss(group_id)
    if boss != curr_boss:
        sv.logger.info('boss变更')
        bot = nonebot.get_bot()
        subDao.update_boss(boss,group_id)
        if send_msg:
            stage = get_boss_stage(lap_num)
            msg = f'{curr_boss}王已被击败\n' if curr_boss else 'BOSS状态更新\n'
            msg += f'当前进度：{stage[1]}面{stage[0]}阶段 {lap_num}周目{boss}王'
            await bot.send_group_msg(group_id=group_id, message=msg)

        # 处理挂树
        if on_tree.get(group_id) != None:
            if len(on_tree[group_id]) > 0:
                off_tree_msg = "以下成员将自动下树：\n"
                for uid in on_tree[group_id]:
                    nonebot.scheduler.remove_job(str(uid))
                    off_tree_msg += f'[CQ:at,qq={uid}]'
                    sv.logger.info(f"{uid}因boss被击败下树")
                on_tree.clear(group_id)
                off_tree_msg += f'''
***当前进度是<<<{boss}>>>王，如果您挂在<<<{boss}>>>王上，请<<<不要>>>结算并重新发送挂树指令！***
您可以通过发送【挂树+数字】来指定提醒时间'''
            await nonebot.get_bot().send_group_msg(group_id=group_id, message=off_tree_msg)
            
        # 通知预约
        await notify_subscribe(boss,group_id)

def get_boss_number(name):
    try:
        boss_name = get_boss_info()
        return boss_name[name]
    except KeyError:
        return '?'


def get_boss_stage(lap_num):
    if lap_num <= 3:
        return (1, 'A')
    elif lap_num <= 10:
        return (2, 'B')
    elif lap_num <= 34:
        return (3, 'C')
    else :
        return (4, 'D')


async def notify_subscribe(boss,group_id):

    # 获取预约成员
    subscribers = subDao.get_subscriber(boss,group_id)
    # 没有预约
    if not subscribers:
        return

    # CQ码
    at_subscriber = ' '.join([f'[CQ:at,qq={qq}]' for qq in subscribers])

    bot = nonebot.get_bot()
    await bot.send_group_msg(group_id=group_id, message=at_subscriber + f'\n你们预约的{boss}王出现了')

    # 清除预约成员
    subDao.clear_subscriber(boss,group_id)

async def get_stat(bot, ev, group_id,date=None):
    data = await get_today_data(date,group_id)
    if not data or len(data) == 0:
        sv.logger.error('API访问失败@get_stat')
        await bot.send(ev, 'API访问失败@get_stat')
    elif 'data' not in data or len(data['data']) == 0:
        sv.logger.error(f'API数据异常{data}@get_stat')
        await bot.send(ev, f'API数据异常\n{data}@get_stat')

    else:
        data = data['data']
        if len(data) == 0:
            await bot.send(ev, f"{'今日' if not date else date}没有出刀记录")
            return
        stat = {3: [], 2.5: [], 2: [], 1.5: [], 1: [], 0.5: [], 0: []}

        reply = []
        reply.append(f"以下是{'今日' if not date else date}的出刀次数统计：")
        total = 0
        for member in data:
            number = member['number']
            total += number
            stat[number].append(member['name'])
        reply.append(f'总计出刀：{total}')
        for k, v in stat.items():
            if len(v) > 0:
                reply.append(f"\n----------\n以下是出了{k}刀的成员：")
                reply.append('|'.join(v))

        # 绘图
        if send_long_msg_as_pic:
            img = await to_image(reply)
            await bot.send(ev, MessageSegment.image(img), at_sender=True)
        else:
            msg = "\n".join(reply)
            await bot.send(ev, msg)


def pil2b64(data):
    bio = BytesIO()
    data = data.convert("RGB")
    data.save(bio, format='JPEG', quality=80)
    base64_str = base64.b64encode(bio.getvalue()).decode()
    return 'base64://' + base64_str


def get_font(size, w='85'):
    return ImageFont.truetype(get_path(f'HYWenHei {w}W.ttf'),
                              size=size)


def get_path(*paths):
    return os.path.join(os.path.dirname(__file__), *paths)


w65 = get_font(26, w=65)


async def to_image(msg_list):

    drow_height = 0
    for msg in msg_list:
        x_drow_segment, x_drow_note_height, x_drow_line_height, x_drow_height = split_text(
            msg)
        drow_height += x_drow_height

    im = Image.new("RGB", (1080, drow_height), '#f9f6f2')
    draw = ImageDraw.Draw(im)
    # 左上角开始
    x, y = 0, 0
    for msg in msg_list:
        drow_segment, drow_note_height, drow_line_height, drow_height = split_text(
            msg)
        for segment, line_count in drow_segment:
            draw.text((x, y), segment, fill=(0, 0, 0), font=w65)
            y += drow_line_height * line_count

    _x, _y = w65.getsize("囗")
    padding = (_x, _y, _x, _y)
    im = ImageOps.expand(im, padding, '#f9f6f2')

    return pil2b64(im)


def split_text(content):
    # 按规定宽度分组
    max_line_height, total_lines = 0, 0
    allText = []
    for text in content.split('\n'):
        segment, line_height, line_count = get_segment(text)
        max_line_height = max(line_height, max_line_height)
        total_lines += line_count
        allText.append((segment, line_count))
    line_height = max_line_height
    total_height = total_lines * line_height
    drow_height = total_lines * line_height
    return allText, total_height, line_height, drow_height


def get_segment(text):
    txt = Image.new('RGBA', (600, 800), (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt)
    # 所有文字的段落
    segment = ""
    max_width = 1080
    # 宽度总和
    sum_width = 0
    # 几行
    line_count = 1
    # 行高
    line_height = 0
    for char in text:
        width, height = draw.textsize(char, w65)
        sum_width += width
        if sum_width > max_width:  # 超过预设宽度就修改段落 以及当前行数
            line_count += 1
            sum_width = 0
            segment += '\n'
        segment += char
        line_height = max(height, line_height)
    if not segment.endswith('\n'):
        segment += '\n'
    return segment, line_height, line_count

async def send_tree_notification(gid, uid, time):
    await nonebot.get_bot().send_group_msg(
        group_id=gid,
        message=f"[CQ:at,qq={uid}]\n距离您报告上树已经过去了{time}分钟，请立刻使用SL或结算！"
    )
    sv.logger.info(f"提醒{uid}下树")





