import os
import aiohttp
import datetime
import pytz
import nonebot
import asyncio
import traceback

from hoshino import Service, priv
from .cbsimple import *
from .dao import SubscribeDao, RecordDao, DailyDao
from apscheduler.triggers.date import DateTrigger

AUTO_LOG_LEVEL = 25

sv = Service('cb-automission', enable_on_default=True, visible=False)
start_date = None
end_date = None

delta = datetime.timedelta(minutes=5)
trigger = DateTrigger(
    run_date=datetime.datetime.now() + delta
)


# 启动后获取一次 start_date 和 end_date
run_time = datetime.datetime.now() + datetime.timedelta(seconds=30)


log_flag = True

@sv.scheduled_job('date', run_date=run_time)
async def gettime_on_start():
    global start_date, end_date
    start_date, end_date = await get_start_end_date()
    bot = nonebot.get_bot()
    sv.logger.log(AUTO_LOG_LEVEL, f"获取工会战期间成功：{start_date}:{end_date}@gettime_on_start")
    


# 每天获取一次 start_date 和 end_date
@sv.scheduled_job('cron', hour=5, minute=5)
async def update_start_end_time():
    global start_date, end_date
    start_date, end_date = await get_start_end_date()
    sv.logger.log(AUTO_LOG_LEVEL, f"获取工会战期间成功：{start_date}:{end_date}@update_start_end_time")

# 手动获取时间
@sv.on_fullmatch('gettime')
async def gettime(bot, ev):
    global start_date, end_date
    start_date, end_date = await get_start_end_date()
    await bot.send(ev, f"当期{start_date}-{end_date}")
    if start_date and end_date:
        return 1
    else:
        return 0
    

# 手动初始化
@sv.on_fullmatch('init', only_to_me=True)
async def init(bot, ev):
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, '权限不足')
        return

    await bot.send(ev, '获取本期时间...')    
    ret = await gettime(bot, ev)
    if ret != 1:
        await bot.send(ev, '未获取到开始结束时间！')
        return
    
    db = SubscribeDao()
    ret = db.init()
    if ret == 1:
        await bot.send(ev, "预约表已重置")
    else:
        await bot.send(ev, "预约表重置失败")
    await update_boss_list(bot, ev)

@sv.scheduled_job('interval', minutes = 2)
async def bossupdater():
    now_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    if not start_date or not end_date or now_date < start_date or now_date > end_date:
        pass # 不在会战期间
    
    else:
        await update()

@sv.scheduled_job('cron', hour = 4, minute=58)
async def get_daily_report():
    now_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    if not start_date or not end_date or now_date < start_date or now_date > end_date:
        pass # 不在会战期间
    
    else:
        await get_report()

@sv.scheduled_job('cron', hour = 4, minute = 57)
async def auto_record():
    now_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    if not start_date or not end_date or now_date < start_date or now_date > end_date:
        pass # 不在会战期间
    
    else:
        await get_record()

@sv.scheduled_job('cron', hour = 0, minute = 10)
async def lat_day_record():
    now_date = (datetime.datetime.now(pytz.timezone('Asia/Shanghai')) - datetime.timedelta(minutes=20)).strftime('%Y-%m-%d')
    if now_date == end_date:
        await get_report()
        await get_record()

async def get_report():
    data = None
    member_data = None
    fail_count = 0

    while fail_count < 3 and not data:
        data = await get_collect()
        fail_count += 1

    fail_count = 0

    while fail_count < 3 and not member_data:
        member_data = await get_today_data()
        fail_count += 1


    if not data or len(data) == 0 or not member_data or len(member_data) == 0:
        sv.logger.error('API访问失败@get_daily_report')
    elif 'data' not in data or len(data['data']) == 0 or 'data' not in member_data:
        sv.logger.error('API数据异常@get_daily_report')
    else:
        try:
            data = data['data']
            clan_info = data['clan_info']
            now = datetime.datetime.now(pytz.timezone('Asia/Shanghai'))
            month = int(now.strftime('%m'))
            date = now.replace(hour=4, minute=59, second=59, microsecond=0, tzinfo=None)
            rank = clan_info['last_ranking']

            member_data = member_data['data']
            recordCount = 0
            totalScore = 0
            totalDamage = 0
            for member in member_data:
                recordCount += member['number']
                totalScore += member['score']
                totalDamage += member['damage']
            
            db = DailyDao()

            db.add_day_report(month, date, rank, recordCount, totalScore, totalDamage)
            sv.logger.log(AUTO_LOG_LEVEL, f'{date}日报已记录@get_daily_report')
        except Exception as e:
            bot = nonebot.get_bot()
            sv.logger.error("自动保存日报失败")

async def get_record():
    date = (datetime.datetime.now(pytz.timezone('Asia/Shanghai')) - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    data = None
    fail_count = 0

    while fail_count < 3 and not data:
        data = await get_today_data()
        fail_count += 1

    if not data or len(data) == 0:
        sv.logger.error('API访问失败@auto_record')
    elif 'data' not in data or len(data['data']) == 0:
        sv.logger.error('API数据异常@auto_record')
    else:
        data = data['data']
        db = RecordDao(start_date.replace('-', ''), end_date.replace('-',''))
        try:
            db.add_record(data)
            sv.logger.log(AUTO_LOG_LEVEL, f'{date} 的出刀已记录@auto_record()')
        except Exception as e:
            bot = nonebot.get_bot()
            sv.logger.error('自动保存出刀记录失败')


async def update():
    global log_flag
    if log_flag:
        sv.logger.info('开始更新boss状态')
        log_flag = False

    data = await get_collect()

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
        await update_boss(boss, lap, send_msg=True)


# @sv.scheduled_job('cron', hour='0', minute='5')
async def cuidao():
    start_date, end_date = await get_start_end_date()
    now_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H%M')
    if now_date < (start_date + ' 05:00') or now_date > (end_date + ' 23:59'):
        pass # 不在会战期间
    
    else:
        sv.logger.info('开始催刀')
        data = await get_today_data()
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


@sv.on_fullmatch('logflag', only_to_me=True)
async def set_log_flag(bot, ev):
    global log_flag
    log_flag = True
    await bot.send(ev, 'OK')

