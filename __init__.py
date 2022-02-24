import datetime
import pytz
import nonebot
from .cbsimple import *
from .dao_multi import SubscribeDao, RecordDao, DailyDao, MemberDao
from apscheduler.triggers.date import DateTrigger


if multigroup:
    from .dao_multi import SubscribeDao, RecordDao, DailyDao, MemberDao
else:
    from .dao import SubscribeDao, RecordDao, DailyDao, MemberDao

subscirbe_text = {}
start_date = None
end_date = None
log_flag = True
AUTO_LOG_LEVEL = 25

helpText1 = '''var cookie=document.cookie;
var Str_Num = cookie.indexOf('session-api');
cookie ='添加 '+cookie.substring(Str_Num);
var ask=confirm('Cookie:'+cookie+'按确认，然后粘贴发送给维护组');
if(ask==true)
    {copy(cookie);
        msg=cookie}
else
    {msg='Cancel'}'''

helpText2 = '''复制上面全部代码，然后打开https://www.bigfun.cn/tools/pcrteam/
在页面上右键检查或者Ctrl+Shift+i
选择控制台（Console），粘贴，回车，在弹出的窗口点确认（点完自动复制）
然后在和维护组私聊，粘贴发送即可
公会战开始当日
1.	请用自己手机上的 bigfun 客户端登录并打开一次 pcr 团队战工具，确保手机app上能正确显示内容。
2.	请发送 init 初始化 bot'''

@sv.on_fullmatch('自动报刀帮助')
async def help(bot, ev):
    await bot.send(ev, helpText1)
    await bot.send(ev, helpText2)

@sv.on_fullmatch('今日出刀')
async def get_today_stat(bot, ev):
    group_id = ev.group_id
    await get_stat(bot,ev,group_id)


@sv.on_fullmatch('昨日出刀')
async def get_yesterday_stat(bot, ev):
    group_id = ev.group_id
    start_date, end_date = await get_start_end_date(ev.group_id)
    if not start_date or not end_date:
        await bot.send(ev, "未获取到会战期间")
        return
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    date = yesterday.strftime('%Y-%m-%d')
    if date < start_date:
        await bot.send(ev, "昨天不是会战期间")
        return
    await get_stat(bot, ev, group_id, date)

@sv.on_fullmatch('昨日日报')
async def yesterday_report(bot, ev):
    group_id = ev.group_id
    now = datetime.datetime.now(pytz.timezone('Asia/Shanghai'))
    if now.hour < 5:
        now -= datetime.timedelta(days=1)
    date = now.replace(hour=4, minute=59, second=59,
                       microsecond=0, tzinfo=None)
    db = DailyDao()
    report = db.get_day_report(date,group_id)
    if not report:
        await bot.send(ev, f"没有找到{date}的记录")
    else:
        report_str = f'''日期：{date.strftime('%Y-%m-%d %H:%M:%S')}
当日最终排名：{report['rank']}
总出刀数：{report['recordCount']}/90
总分数：{report['totalScore']}
总伤害：{report['totalDamage']}
'''
        await bot.send(ev, report_str)

@sv.on_fullmatch('状态')
async def get_boss_status(bot, ev):
    group_id = ev.group_id
    data = await get_collect(group_id)
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
        boss_num = get_boss_number(boss_info['name'])
        boss_hp = boss_info['current_life']
        boss_max_hp = boss_info['total_life']
        await update_boss(boss_num, boss_info['lap_num'],group_id)
        status_str = f'''{clan_info['name']} 排名{clan_info['last_ranking']}
当前进度：
{stage_char}面{stage_num}阶段 {boss_info['lap_num']}周目{boss_num}王 {boss_info['name']}
HP: {number_formatter(boss_hp)}/{number_formatter(boss_max_hp)} {boss_hp/boss_max_hp:.1%}
*查询结果存在延迟 请以游戏内为准'''

        await bot.send(ev, status_str)


@sv.on_fullmatch(('sl', 'SL', "Sl"))
async def record_sl(bot, ev):
    uid = ev.user_id
    group_id = ev.group_id
    result = slDao.add_sl(uid,group_id)
    if result == 0:
        await bot.send(ev, 'SL已记录', at_sender=True)
    elif result == 1:
        await bot.send(ev, '今天已经SL过了', at_sender=True)
    else:
        await bot.send(ev, '数据库错误 请查看log')


@sv.on_fullmatch(('sl?', 'SL?', 'sl？', 'SL？'))
async def has_sl(bot, ev):
    result = slDao.check_sl(ev.user_id,ev.group_id)
    if result == 0:
        await bot.send(ev, '今天还没有使用过SL', at_sender=True)
    elif result == 1:
        await bot.send(ev, '今天已经SL过了', at_sender=True)
    else:
        await bot.send(ev, '数据库错误 请查看log')

@sv.on_rex(r'^预约\s?(\d)\s?(\S*)')
async def subscirbe(bot, ev):
    group_id = ev.group_id
    uid = ev.user_id
    match = ev['match']
    boss = int(match.group(1))

    if boss > 5 or boss < 1:
        await bot.send(ev, "不约，滚")
        return
    result = subDao.add_subscribe(uid, boss,group_id)
    subscirbe_text[f'{uid}+{boss}+{group_id}'] = match.group(2)
    if result == 1:
        if boss in (1, 2):
            msg = '虽然我觉得会来不及通知你，但还是给你预约上了'
        else:
            msg = '预约成功'
        await bot.send(ev, msg, at_sender=True)
    else:
        await bot.send(ev, '预约失败', at_sender=True)

@sv.on_fullmatch('预约表', only_to_me=False)
async def form_subscribe(bot, ev):
    i = 1
    a = 0
    group_id = ev.group_id
    FormSubscribe = "当前预约列表"
    subscribers = []
    while i < 6:
        subscribersID = subDao.get_subscriber(i,group_id)
        if not subscribersID:
            a = a+1
        else:
           for qq in subscribersID :
                info = await bot.get_group_member_info(group_id=ev.group_id,user_id =qq)
                if not info["card"]:
                    name = "nickname"
                else :
                     name = "card"
                if subscirbe_text.get(f'{qq}+{i}+{group_id}') != None :
                    text = f'{qq}+{i}+{group_id}'
                    subscribers.append(f'{info[name]}:{subscirbe_text[text]}')
                else :
                    subscribers.append(info[name])
                FormSubscribe = FormSubscribe + f'\n{subscribers}预约了{i}王'
        subscribers = []
        i = i+1 
    if a == 5:
       await bot.send(ev, "无人预约呢喵" )
    else:
        await bot.send(ev, FormSubscribe)

@sv.on_rex(r'^取消预约\s?(\d)')
async def subscirbe(bot, ev):
    uid = ev.user_id
    match = ev['match']
    boss = int(match.group(1))
    group_id = ev.group_id
    if boss > 5 or boss < 1:
        await bot.send(ev, "爬爬")
        return
    for m in ev['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            if not priv.check_priv(ev, priv.ADMIN):
                await bot.send(ev, '权限不足')
            else:
                uid = int(m.data['qq'])          
    subDao.delete_subscriber(uid,boss,group_id)
    if subscirbe_text.get(f'{uid}+{boss}+{group_id}') != None :
        subscirbe_text.pop(f'{uid}+{boss}+{group_id}')
    await bot.send(ev, '取消成功', at_sender=True)

@sv.on_rex(r'^清空预约\s?(\d)')
async def subscirbe(bot, ev):
    group_id = ev.group_id
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, '权限不足')
    else:
        match = ev['match']
        boss = int(match.group(1))
        if boss > 5 or boss < 1:
            await bot.send(ev, "爬爬")
            return
        subDao.clear_subscriber(boss,group_id)
        await bot.send(ev, '清除成功', at_sender=True)

@sv.on_rex(r'^[上挂]树\s*(\d*)$')
async def climb_tree(bot, ev):
    uid = ev.user_id
    group_id = ev.group_id

    if on_tree.get(group_id) is None:
        on_tree[group_id]=[]

    if uid in on_tree[group_id]:
        await bot.send(ev, "您已经在树上了", at_sender=True)
        return

    match = ev['match']
    time = match.group(1)
    if not time or len(time) == 0:
        time = 55
    else:
        time = int(time)

    reply = f"上树成功，将在{time}分钟后提醒您下树"

    trigger = DateTrigger(
        run_date=datetime.datetime.now() + datetime.timedelta(minutes=time)
    )
    id = f"{uid}@{group_id}"
    nonebot.scheduler.add_job(
        func=send_tree_notification,
        trigger=trigger,
        args=(group_id, uid, time),
        misfire_grace_time=10,
        id=id,
        replace_existing=True
    )
    on_tree[group_id].append(uid)
    sv.logger.info(f"{uid}上树")
    await bot.send(ev, reply, at_sender=True)

@sv.on_fullmatch('下树')
async def off_tree(bot, ev):
    uid = ev.user_id
    group_id = ev.group_id
    if on_tree.get(group_id) is not None:
        if uid not in on_tree[group_id]:
            await bot.send(ev, "您似乎不在树上", at_sender=True)
            return
    else:
        await bot.send(ev, "您似乎不在树上", at_sender=True)
        return

    id = f"{uid}@{group_id}"
    nonebot.scheduler.remove_job(id)
    on_tree[group_id].remove(uid)
    sv.logger.info(f"{uid}主动下树")
    await bot.send(ev, "下树成功", at_sender=True)

@sv.on_fullmatch('查树')
async def check_tree(bot: HoshinoBot, ev):
    group_id = ev.group_id

    if on_tree.get(group_id) == None:
        on_tree[group_id]=[]

    if len(on_tree[group_id]) == 0:
        await bot.send(ev, "目前树上空空如也")
        return
    reply = f'树上目前有{len(on_tree[group_id])}人'

    for uid in on_tree[group_id]:
        info = await bot.get_group_member_info(group_id=group_id, user_id=uid)
        name = info['card'] if info['card'] and len(
            info['card']) > 0 else info['nickname']
        reply += f'\n{name}'
    await bot.send(ev, reply)

@sv.on_fullmatch('更新boss列表')
async def update_boss_list(bot, ev):
    data = await get_boss_list(ev.group_id)
    if not data or len(data) == 0:
        sv.logger.error('API访问失败@update_boss_list')
    elif 'data' not in data or len(data['data']) == 0:
        sv.logger.error(f'API数据异常\n{data}@update_boss_list')
    else:
        data = data['data']
        constellation = data['name']
        boss_list = data['boss_list']
        boss_dict = {boss['boss_name']:int(boss['id'][-1]) for boss in boss_list}

        
        #写入config.json
        config = util.load_config(__file__)
        config['boss_name'] = boss_dict
        config_file = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)
        
        await bot.send(ev, f"已更新{constellation} BOSS 列表")

@sv.on_prefix('注册')
async def register(bot, ev):
    uid = None
    name = None
    group_id = ev.group_id
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

    db_name = db.get_name_from_qq(uid,group_id)

    if db_name is not None:
        await bot.send(ev, f'已存在注册信息：{db_name}，如欲更新请使用[更新注册]指令')
        return

    if db.register(uid, name,group_id) == 1:
        await bot.send(ev, '注册成功')
    else:
        await bot.send(ev, '注册失败')

@sv.on_fullmatch('查看注册信息')
async def get_register_info(bot, ev):
    uid = None
    group_id = ev.group_id
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
    name = db.get_name_from_qq(uid,group_id)
    if not name:
        await bot.send(ev, '未找到注册信息，请先注册！')
    else:
        await bot.send(ev, f'[CQ:at,qq={uid}] 已注册为 {name}')

@sv.on_prefix(('更新注册', '注册更新'))
async def update_register(bot, ev):
    uid = None
    name = None
    group_id = ev.group_id
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
    if db.get_name_from_qq(uid,group_id) is None:
        await bot.send(ev, '未找到注册信息，请先注册！')
        return

    if db.update_info(uid, name,group_id) == 1:
        await bot.send(ev, '更新成功')
    else:
        await bot.send(ev, '更新失败')

@sv.on_prefix('删除成员')
async def delete_member(bot, ev):
    group_id = ev.group_id
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
    name = db.get_name_from_qq(uid,group_id)
    if not name:
        await bot.send(ev, '未找到注册信息')
        return

    if db.leave(uid,group_id) == 1:
        await bot.send(ev, f'删除{name}成功')
    else:
        await bot.send(ev, f'删除{name}失败')

@sv.on_rex(r'^找人\s?(\S+)$')
async def find_qq_by_name(bot, ev):
    group_id = ev.group_id
    match = ev['match']
    name = match.group(1)
    db = MemberDao()
    qq = db.get_qq_from_name(name,group_id)
    if not qq:
        await bot.send(ev, f"没有找到{name}的注册信息")
    else:
        await bot.send(ev, f'{name}是[CQ:at,qq={qq}]')

# 手动获取时间
@sv.on_fullmatch('gettime')
async def gettime(bot, ev):
    global start_date, end_date
    start_date, end_date = await get_start_end_date(ev.group_id)
    await bot.send(ev, f"当期{start_date}-{end_date}")
    if start_date and end_date:
        return 1
    else:
        return 0


#TODO 同时初始化所有群
# 手动初始化
@sv.on_fullmatch('init', only_to_me=True)
async def init(bot, ev):
    group_id = ev.group_id
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, '权限不足')
        return

    await bot.send(ev, '获取本期时间...')    
    ret = await gettime(bot, ev)
    if ret != 1:
        await bot.send(ev, '未获取到开始结束时间！')
        return
    
    db = SubscribeDao()
    ret = db.init(group_id)
    if ret == 1:
        await bot.send(ev, "预约表已重置")
    else:
        await bot.send(ev, "预约表重置失败")
    await update_boss_list(bot, ev)

@sv.on_fullmatch('催刀')
async def cuidao(bot,ev):
    group_id = ev.group_id
    start_date, end_date = await get_start_end_date(group_id)
    now_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H%M')
    if now_date < (start_date + ' 05:00') or now_date > (end_date + ' 23:59'):
        error = '不在会战期间'
        await bot.send_group_msg(group_id=group_id, message=error)
    
    else:
        sv.logger.info('开始催刀')
        data = await get_today_data(None,group_id)
        if not data or len(data) == 0:
            sv.logger.error('API访问失败')
        elif 'data' not in data or len(data['data']) == 0:
            sv.logger.error('API数据异常')


        else:
            data = data['data']
            stat_str = [member['name'] for member in data if member['number'] < 3]
            msg = f"截至{now_date}CST，还有以下成员没有出满3刀，请记得出刀：\n" + "\n".join(stat_str) + "\n*查询结果可能存在延迟 请以游戏内为准"
            bot = nonebot.get_bot()
            await bot.send_group_msg(group_id=group_id, message=msg)




################################
##            AUTO            ##
################################

delta = datetime.timedelta(minutes=5)
trigger = DateTrigger(
    run_date=datetime.datetime.now() + delta
)

# 启动后获取一次 start_date 和 end_date
run_time = datetime.datetime.now() + datetime.timedelta(seconds=15)

@sv.scheduled_job('date', run_date=run_time)
async def gettime_on_start():
    global start_date, end_date
    group_ids = groupids()
    start_date, end_date = await get_start_end_date(group_ids[0])
    bot = nonebot.get_bot()
    sv.logger.log(AUTO_LOG_LEVEL, f"获取工会战期间成功：{start_date}:{end_date}@gettime_on_start")

# 每天获取一次 start_date 和 end_date
@sv.scheduled_job('cron', hour=9)
async def update_start_end_time():
    global start_date, end_date
    group_ids = groupids()
    start_date, end_date = await get_start_end_date(group_ids[0])
    sv.logger.log(AUTO_LOG_LEVEL, f"获取工会战期间成功：{start_date}:{end_date}@update_start_end_time")

async def update():
    group_ids = groupids()
    for group_id in group_ids:
        global log_flag
        if log_flag:
            sv.logger.info('开始更新boss状态')
            log_flag = False

        data = await get_collect(group_id)

        if not data or len(data) == 0:
            sv.logger.error('API访问失败@update')
        elif 'data' not in data or len(data['data']) == 0:
            sv.logger.error('API数据异常@update')
    
        else:

            data = data['data']
            # boss 状态
            boss_info = data['boss_info']
            boss = get_boss_number(boss_info['name'])
            lap = boss_info['lap_num']
            await update_boss(boss, lap, group_id,send_msg=True)

@sv.scheduled_job('interval', minutes = 2)
async def bossupdater():
    now_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    if not start_date or not end_date or now_date < start_date or now_date > end_date:
        pass # 不在会战期间
    
    else:
        await update()

@sv.on_fullmatch('logflag', only_to_me=True)
async def set_log_flag(bot, ev):
    global log_flag
    log_flag = True
    await bot.send(ev, 'OK')



