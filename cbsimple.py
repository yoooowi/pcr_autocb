import aiohttp
import datetime
from nonebot.command import group
import pytz
import traceback
import nonebot
import random
import urllib.request, json 
from hoshino import HoshinoBot, Service, util, priv
from .dao import DailyDao, MemberDao, SLDao, SubscribeDao, RecordDao
from apscheduler.triggers.date import DateTrigger



MEMBER_API = "https://www.bigfun.cn/api/feweb?target=gzlj-clan-day-report/a&size=30"
BOSS_API = "https://www.bigfun.cn/api/feweb?target=gzlj-clan-day-report-collect/a"

sv = Service('clanbattle_simple', enable_on_default=True, visible=True)

slDao = SLDao()
subDao = SubscribeDao()
group_id = util.load_config(__file__)['group']

on_tree = []

def cookie():
    return util.load_config(__file__)["cookie"]


def get_boss_info():
    with urllib.request.urlopen("https://raw.githubusercontent.com/yoooowi/pcr_autocb/master/config.json") as url:
        data = json.loads(url.read().decode())
    return data


async def get_today_data(date:str=None):
    api = MEMBER_API if not date else  f'{MEMBER_API}&date={date}'
    try:
        async with aiohttp.ClientSession(cookies=cookie()) as session:
            async with session.get(api) as resp:
                return await resp.json(content_type='application/json')
    except:
        traceback.print_exc()
    return None


async def get_collect():
    try:
        async with aiohttp.ClientSession(cookies=cookie()) as session:
            async with session.get(BOSS_API) as resp:
                return await resp.json(content_type='application/json')
    except:
        traceback.print_exc()
    return None

async def get_start_end_date():
    data = await get_collect()
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


async def update_boss(boss, lap_num, send_msg=False):
    curr_boss = subDao.curr_boss()
    if boss != curr_boss:
        sv.logger.info('boss变更')
        bot = nonebot.get_bot()
        subDao.update_boss(boss)
        if send_msg:
            stage = get_boss_stage(lap_num)
            msg = f'{curr_boss}王已被击败\n' if curr_boss else 'BOSS状态更新\n'
            msg += f'当前进度：{stage[1]}面{stage[0]}阶段 {lap_num}周目{boss}王'
            await bot.send_group_msg(group_id=group_id, message = msg)

        # 处理挂树
        if len(on_tree) > 0:
            off_tree_msg = "以下成员将自动下树：\n"
            for uid in on_tree:
                nonebot.scheduler.remove_job(str(uid))
                off_tree_msg += f'[CQ:at,qq={uid}]'
                sv.logger.info(f"{uid}因boss被击败下树")
            on_tree.clear()
            off_tree_msg += f'''
***当前进度是<<<{boss}>>>王，如果您挂在<<<{boss}>>>王上，请<<<不要>>>结算并重新发送挂树指令！***
您可以通过发送【挂树+数字】来指定提醒时间'''
            await nonebot.get_bot().send_group_msg(group_id=group_id, message=off_tree_msg)

        # 通知预约
        await notify_subscribe(boss)




def get_boss_number(hp):
    boss_hp = get_boss_info()["boss_hp_to_num"]
    return boss_hp[str(hp)]

def get_boss_stage(lap_num):
    if lap_num <= 3:
        return (1, 'A')
    elif lap_num <= 10:
        return (2, 'B')
    else:
        return (3, 'C')


async def notify_subscribe(boss):

    # 获取预约成员
    subscribers = subDao.get_subscriber(boss)
    # 没有预约
    if not subscribers:
        return
        
    # CQ码
    at_subscriber = ' '.join([f'[CQ:at,qq={qq}]' for qq in subscribers])

    bot = nonebot.get_bot()
    await bot.send_group_msg(group_id=group_id, message= at_subscriber + f'\n你们预约的{boss}王出现了')

    # 清除预约成员
    subDao.clear_subscriber(boss)



@sv.on_fullmatch('今日出刀')
async def get_today_stat(bot, ev):
    await get_stat(bot, ev)

@sv.on_fullmatch('昨日出刀')
async def get_yesterday_stat(bot, ev):
    start_date, end_date = await get_start_end_date()
    if not start_date or not end_date:
        await bot.send(ev, "未获取到会战期间")
        return
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    date = yesterday.strftime('%Y-%m-%d')
    if date < start_date:
        await bot.send(ev, "昨天不是会战期间")
        return
    await get_stat(bot, ev, date)


async def get_stat(bot, ev, date=None):
    data = await get_today_data(date)
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
        stat = {3:[], 2.5:[], 2:[], 1.5:[], 1:[], 0.5:[], 0:[]}

        reply = f"以下是{'今日' if not date else date}的出刀次数统计：\n"
        total = 0
        for member in data:
            number = member['number']
            total += number
            stat[number].append(member['name'])
        reply += f'总计出刀：{total}'
        for k, v in stat.items():
            if len(v) > 0:
                reply += f"\n----------\n以下是出了{k}刀的成员：\n"
                reply += '|'.join(v)
        await bot.send(ev, reply)



@sv.on_fullmatch('状态')
async def get_boss_status(bot, ev):
    data = await get_collect()

    if not data or len(data) == 0:
        sv.logger.error('API访问失败@get_boss_status')
        await bot.send(ev, 'API访问失败@get_boss_status')
    elif 'data' not in data or len(data['data']) == 0:
        sv.logger.error(f'API数据异常{data}@get_boss_status')
        await bot.send(ev, f'API数据异常\n{data}@get_boss_status')

    else:
        now = datetime.datetime.now(pytz.timezone('Asia/Shanghai'))
        date = now.strftime('%Y-%m-%d')
        data = data['data']
        # print (f'date:{date}, data:{data}')
        if 'day_list' not in data or date not in data['day_list']:
            await bot.send(ev, "现在似乎不是会战期间")
            return
        

        clan_info = data['clan_info']
        boss_info = data['boss_info']
        stage_num, stage_char = get_boss_stage(boss_info['lap_num'])
        boss_num = get_boss_number(boss_info['total_life'])
        boss_hp = boss_info['current_life']
        boss_max_hp = boss_info['total_life']
        await update_boss(boss_num, boss_info['lap_num'])
        status_str = f'''{clan_info['name']} 排名{clan_info['last_ranking']}
当前进度：
{stage_char}面{stage_num}阶段 {boss_info['lap_num']}周目{boss_num}王 {boss_info['name']}
HP: {util.number_formatter(boss_hp)}/{util.number_formatter(boss_max_hp)} {boss_hp/boss_max_hp:.1%}
*查询结果存在延迟 请以游戏内为准'''

        await bot.send(ev, status_str)



@sv.on_fullmatch(('sl', 'SL', "Sl"))
async def record_sl(bot, ev):
    result = slDao.add_sl(ev.user_id)
    if result == 0:
        await bot.send(ev, 'SL已记录', at_sender=True)
    elif result == 1:
        await bot.send(ev, '今天已经SL过了', at_sender=True)
    else:
        await bot.send(ev, '数据库错误 请查看log')

@sv.on_fullmatch(('sl?','SL?','sl？', 'SL？'))
async def has_sl(bot, ev):
    result = slDao.check_sl(ev.user_id)
    if result == 0:
        await bot.send(ev, '今天还没有使用过SL', at_sender=True)
    elif result == 1:
        await bot.send(ev, '今天已经SL过了', at_sender=True)
    else:
        await bot.send(ev, '数据库错误 请查看log')


@sv.on_rex(r'^预约\s?(\d)')
async def subscirbe(bot, ev):
    match = ev['match']
    boss = int(match.group(1))
    if boss > 5 or boss < 1:
        bot.send(ev, "不约，滚")
        return
    uid = ev.user_id
    result = subDao.add_subscribe(uid, boss)
    if result == 1:
        if boss in (1, 2):
            msg = '虽然我觉得它活不过一个状态更新周期，但还是给你预约上了'
        else:
            msg = '预约成功'
        await bot.send(ev, msg, at_sender=True)
    else:
        await bot.send(ev, '预约失败', at_sender=True)

@sv.on_fullmatch('昨日日报')
async def yesterday_report(bot, ev):
    now = datetime.datetime.now(pytz.timezone('Asia/Shanghai'))
    if now.hour < 5:
        now -= datetime.timedelta(days=1)
    date = now.replace(hour=4, minute=59, second=59, microsecond=0, tzinfo=None)
    db = DailyDao()
    report = db.get_day_report(date)
    if not report:
        await bot.send(ev, f"没有找到{date}的记录")
    else:
        report_str = f'''日期：{date.strftime('%Y-%m-%d')}
当日最终排名：{report['rank']}
总出刀数：{report['recordCount']}/90
总分数：{report['totalScore']}
总伤害：{report['totalDamage']}
'''
        await bot.send(ev, report_str)


@sv.on_rex(r'^[上挂]树\s*(\d*)$')
async def climb_tree(bot, ev): 
    uid = ev.user_id
    if uid in on_tree:
        await bot.send(ev, "您已经在树上了", at_sender=True)
        return

    match = ev['match']
    time = match.group(1)
    if not time or len(time) == 0:
        time = 55
    else:
        time = int(time)
        if time > 55:
            await bot.send(ev, "挂树时间不得超过55分钟。已为您自动设为55分钟。", at_sender=True)
            time = 55

    roll = random.randint(1, 100)
    if roll < 20:
        reply = "哈哈"
    elif roll < 30:
        reply = "你怎么又挂树了"
    else:
        reply = f"上树成功，将在{time}分钟后提醒您下树"

    trigger = DateTrigger(
        run_date = datetime.datetime.now() + datetime.timedelta(minutes=time)
    )
    id = str(uid)
    nonebot.scheduler.add_job(
        func=send_tree_notification,
        trigger=trigger,
        args=(group_id, uid, time),
        misfire_grace_time=10,
        id=id,
        replace_existing=True
    )
    on_tree.append(uid)
    sv.logger.info(f"{uid}上树")
    await bot.send(ev, reply, at_sender=True)

@sv.on_fullmatch('下树')
async def off_tree(bot, ev):
    uid = ev.user_id
    if uid not in on_tree:
        await bot.send(ev, "您似乎不在树上", at_sender=True)
        return
    
    id = str(uid)
    nonebot.scheduler.remove_job(id)
    on_tree.remove(uid)
    sv.logger.info(f"{uid}主动下树")
    await bot.send(ev, "下树成功", at_sender=True)

async def send_tree_notification(gid, uid, time):
    await nonebot.get_bot().send_group_msg(
        group_id=gid,
        message=f"[CQ:at,qq={uid}]\n距离您报告上树已经过去了{time}分钟，请立刻使用SL或结算！"
        )
    sv.logger.info(f"提醒{uid}下树")

@sv.on_fullmatch('查树')
async def check_tree(bot:HoshinoBot, ev):
    if len(on_tree) == 0:
        await bot.send(ev, "目前树上空空如也")
        return
    roll = random.randint(1, 100)
    if roll < 20:
        reply = f'树上目前有{len(on_tree)}只🐒'
    else:
        reply = f'树上目前有{len(on_tree)}人'
    
    for uid in on_tree:
        info = await bot.get_group_member_info(group_id=group_id, user_id=uid)
        name = info['card'] if info['card'] and len(info['card']) > 0 else info['nickname']
        reply += f'\n{name}'
    await bot.send(ev, reply)


@sv.on_fullmatch(('作业表', '作业'))
async def refs(bot, ev):
    msg = '''一阶段作业
>>> http://t.cn/A653chPl
二阶段作业
>>> http://t.cn/A6IRD7js
三阶段作业
>>> http://t.cn/A6cJ7to3
分刀器
>>> https://www.aikurumi.cn/'''
    await bot.send(ev, msg)

@sv.on_rex(r'手动记录(\d\d\d\d-\d\d-\d\d)')
async def manual_record(bot, ev):
    match = ev['match']
    date = match.group(1)
    sv.logger.info(f"Date matched:{date}")
    start_date, end_date = await get_start_end_date()
    sv.logger.info(f"Start/End:{start_date}-{end_date}")
    data = await get_today_data(date)
    if not data or len(data) == 0:
        sv.logger.error('API访问失败@manual_record')
    elif 'data' not in data or len(data['data']) == 0:
        sv.logger.error(f'API数据异常{data}@manual_record')
    else:
        data = data['data']
        db = RecordDao(start_date.replace('-', ''), end_date.replace('-',''))
        try:
            db.add_record(data)
            sv.logger.info("记录成功")
        except Exception as e:
            raise


@sv.on_prefix('注册')
async def register(bot, ev):
    uid = None
    name = None
    for m in ev['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            uid = int(m.data['qq'])
        elif m.type == 'text':
            name = str(m.data['text']).strip()
    if uid is None:
        uid = ev['user_id']
    else:
        if not priv.check_priv(ev, priv.ADMIN):
            await bot.send(ev, '为他人注册需要群主权限')
            return
    if name is None or len(name) == 0:
        await bot.send(ev, '请提供游戏昵称')
        return 


    db = MemberDao()

    db_name = db.get_name_from_qq(uid)

    if db_name is not None:
        await bot.send(ev, f'已存在注册信息：{db_name}，如欲更新请使用[更新注册]指令')
        return

    if db.register(uid, name) == 1:
        await bot.send(ev, '注册成功')
    else:
        await bot.send(ev, '注册失败')

@sv.on_fullmatch('查看注册信息')
async def get_register_info(bot, ev):
    uid = None
    for m in ev['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            uid = int(m.data['qq'])
    if uid is None:
        uid = ev['user_id']
    else:
        if not priv.check_priv(ev, priv.SUPERUSER):
            await bot.send(ev, '为他人注册需要群主权限')
            return
    
    db = MemberDao()
    name = db.get_name_from_qq(uid)
    if not name:
        await bot.send(ev, '未找到注册信息，请先注册！')
    else:
        await bot.send(ev, f'[CQ:at,qq={uid}] 已注册为 {name}')


@sv.on_prefix(('更新注册', '注册更新'))
async def update_register(bot, ev):
    uid = None
    name = None
    for m in ev['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            uid = int(m.data['qq'])
        elif m.type == 'text':
            name = str(m.data['text']).strip()
    if uid is None:
        uid = ev['user_id']
    else:
        if not priv.check_priv(ev, priv.SUPERUSER):
            await bot.send(ev, '为他人注册需要群主权限')
            return
    if name is None:
        await bot.send(ev, '请提供游戏昵称')
        return 


    db = MemberDao()
    if db.get_name_from_qq(uid) is None:
        await bot.send(ev, '未找到注册信息，请先注册！')
        return

    if db.update_info(uid, name) == 1:
        await bot.send(ev, '更新成功')
    else:
        await bot.send(ev, '更新失败')

@sv.on_prefix('删除成员')
async def delete_member(bot, ev):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, "权限不足")
        return


    uid = None
    for m in ev['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            uid = int(m.data['qq'])
            break
        elif m.type == 'text':
            uid = str(m.data['text']).strip()
            if uid.isdigit():
                uid = int(uid)
                break
            else:
                await bot.send(ev, "输入格式不正确")
                return

    db = MemberDao()
    name = db.get_name_from_qq(uid)
    if not name:
        await bot.send(ev, '未找到注册信息')
        return 

    if db.leave(uid) == 1:
        await bot.send(ev, f'删除{name}成功')
    else:
        await bot.send(ev, f'删除{name}失败')


@sv.on_rex(r'^找人\s?(\S+)$')
async def find_qq_by_name(bot, ev):
    match = ev['match']
    name = match.group(1)
    db = MemberDao()
    qq = db.get_qq_from_name(name)
    if not qq:
        await bot.send(ev, f"没有找到{name}的注册信息")
    else:
        await bot.send(ev, f'{name}是[CQ:at,qq={qq}]')
