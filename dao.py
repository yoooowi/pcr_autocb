import sqlite3
import os
import datetime
import pytz
import urllib.request
import json
from hoshino import util


DB_PATH = os.path.expanduser('~/.hoshino/cbsimple.db')

def get_boss_info():
    config = util.load_config(__file__)
    data = config['boss_name']
    return data

def get_boss_num(boss_list, boss_name):
    if boss_name in boss_list:
        return boss_list[boss_name]
    else:
        return 0

def pcr_date():
    now = datetime.datetime.now(pytz.timezone('Asia/Shanghai'))
    if now.hour < 5:
        now -= datetime.timedelta(days=1)
    pcr_date = now.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None) #用12点做基准
    return pcr_date

class SqliteDao(object):
    def __init__(self, table, columns, fields):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._dbpath = DB_PATH
        self._table = table
        self._columns = columns
        self._fields = fields
        self._create_table()


    def _create_table(self):
        sql = "CREATE TABLE IF NOT EXISTS {0} ({1})".format(self._table, self._fields)
        # logging.getLogger('SqliteDao._create_table').debug(sql)
        with self._connect() as conn:
            conn.execute(sql)


    def _connect(self):
        # detect_types 中的两个参数用于处理datetime
        return sqlite3.connect(self._dbpath, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)



class SLDao(SqliteDao):
    def __init__(self):
        super().__init__(
            table='sl',
            columns='uid, last_sl',
            fields='''
            uid INT PRIMARY KEY,
            last_sl TIMESTAMP
            ''')


    # 0 -> 记录成功
    # 1 -> 当天已有SL记录
    # 2 -> 其它错误
    def add_sl(self, uid, group_id = None):
        with self._connect() as conn:
            try:
                ret = conn.execute("SELECT uid, last_sl FROM sl WHERE uid = ?", (uid,)).fetchone()

                # 该成员没有使用过SL
                if not ret:
                    conn.execute('INSERT INTO sl (uid, last_sl) VALUES (?, ?)', (uid, pcr_date()))
                    return 0

                last_sl = ret[1]

                # 今天已经有SL记录
                if last_sl == pcr_date():
                    return 1

                # 今天没有SL
                else:
                    conn.execute('UPDATE sl SET last_sl = ? WHERE uid = ?', (pcr_date(), uid))
                    return 0

            except (sqlite3.DatabaseError) as e:
                raise

    # 0 -> 没有SL
    # 1 -> 有SL
    # 2 -> Error
    def check_sl(self, uid, group_id):
        with self._connect() as conn:
            try:
                ret = conn.execute("SELECT uid, last_sl FROM sl WHERE uid = ?", (uid,)).fetchone()

                # 该成员没有使用过SL
                if not ret:
                    return 0

                last_sl = ret[1]

                # 今天已经有SL记录
                if last_sl == pcr_date():
                    return 1

                # 今天没有SL
                else:
                    return 0

            except (sqlite3.DatabaseError) as e:
                raise

# uid -1 是当前 BOSS
class SubscribeDao(SqliteDao):
    def __init__(self):
        super().__init__(
            table='subscribe',
            columns='uid, boss',
            fields='''
            uid INT NOT NULL,
            boss INT NOT NULL
            ''')

    def init(self, group_id=None):
        with self._connect() as conn:
            try:
                conn.execute("DELETE FROM subscribe where 1=1")
                conn.execute("INSERT INTO subscribe (uid, boss) VALUES (-1, 1)")
                return 1

            except (sqlite3.DatabaseError) as e:
                print(e)
                return 0

    def curr_boss(self, group_id):
        with self._connect() as conn:
            try:
                ret = conn.execute("SELECT boss FROM subscribe WHERE uid = ?", (-1,)).fetchone()
                if not ret:
                    return None
                return ret[0]

            except (sqlite3.DatabaseError) as e:
                raise

    def get_subscriber(self, boss, group_id):
        with self._connect() as conn:
            try:
                ret = conn.execute("SELECT DISTINCT uid FROM subscribe WHERE boss = ? AND uid <> -1", (boss,)).fetchall()
                return [r[0] for r in ret]

            except (sqlite3.DatabaseError) as e:
                raise

    # 1 -> Success
    # 0 -> Fail
    def clear_subscriber(self, boss=None, group_id=None):
        sql = "DELETE FROM subscribe WHERE uid <> -1" if not boss else \
            f"DELETE FROM subscribe WHERE boss = {boss} AND uid <> -1"
        with self._connect() as conn:
            try:
                conn.execute(sql)
                return 1

            except (sqlite3.DatabaseError) as e:
                return 0

    def add_subscribe(self, uid, boss, group_id):
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO subscribe (uid, boss) VALUES (?, ?) ", (uid, boss))
                return 1

            except (sqlite3.DatabaseError) as e:
                return 0

    def update_boss(self, boss, group_id):
        with self._connect() as conn:
            try:
                conn.execute("UPDATE subscribe SET boss=? WHERE uid = -1 ", (boss,))
                return 1

            except (sqlite3.DatabaseError) as e:
                return 0

    def delete_subscriber(self,uid=None,boss=None,group_id=None):
        sql =  f"DELETE FROM subscribe WHERE boss = {boss} AND uid = {uid}"
        with self._connect() as conn:
            try:
                conn.execute(sql)
                return 1

            except (sqlite3.DatabaseError) as e:
                return 0
class RecordDao(SqliteDao):
    def __init__(self, start=None, end=None):
        super().__init__(
            table=f'records',
            columns='name, time, boss, damage, flag',
            fields='''
            name VARCHAR(16) NOT NULL,
            time TIMESTAMP NOT NULL,
            lap INT NOT NULL,
            boss VARCHAR(16) NOT NULL,
            damage INT NOT NULL,
            flag INT NOT NULL
            ''')

    def add_record(self, records, group_id):
        
        with self._connect() as conn:
            try:
                for member in records:
                    name = member['name']

                    for record in member['damage_list']:
                        timestamp = record['datetime']
                        boss = record['boss_name']
                        time = datetime.datetime.fromtimestamp(timestamp, pytz.timezone('Asia/Shanghai'))
                        time = time.replace(tzinfo=None)
                        lap = record['lap_num']
                        damage = record['damage']
                        kill = record['kill']
                        reimburse = record['reimburse']
                        reimburse <<= 1
                        flag = kill | reimburse

                        conn.execute(f"INSERT INTO {self._table} VALUES (?,?,?,?,?,?)", (name, time, lap, boss, damage, flag))
                return 1
                        

            except (sqlite3.DatabaseError) as e:
                raise

    def get_all_records(self, group_id):
        with self._connect() as conn:
            try:
                result = conn.execute(f"SELECT name, time, lap, boss, damage, flag FROM {self._table}").fetchall()
                if not result:
                    return None
                return [{'name':r[0], 'time':r[1], 'lap':r[2], 'boss':r[3], \
                    'damage':r[4], 'flag':r[5]} for r in result]

            except (sqlite3.DatabaseError) as e:
                raise



    def get_day_rcords(self, date:datetime.datetime, group_id):

        date = date.replace(hour=5, minute=0, second=0, microsecond=0)
        tomorrow = date + datetime.timedelta(days=1)

        with self._connect() as conn:
            try:
                result = conn.execute(f"SELECT name, time, lap, boss, damage, flag FROM {self._table} WHERE time BETWEEN ? AND ?", \
                    (date, tomorrow)).fetchall()
                if not result:
                    return None
                return [{'name':r[0], 'time':r[1], 'lap':r[2], 'boss':r[3], \
                    'damage':r[4], 'flag':r[5]} for r in result]

            except (sqlite3.DatabaseError) as e:
                raise

    def get_member_monthly_record(self, name, start, group_id):
        
        boss_list = get_boss_info()

        with self._connect() as conn:
            try:
                result = conn.execute(f"SELECT name, time, lap, boss, damage, flag FROM {self._table} WHERE time > ? AND name = ? ORDER BY time", \
                    (start, name)).fetchall()
                if not result:
                    return None
                return [{'name':r[0], 'time':r[1], 'lap':r[2], 'boss':get_boss_num(boss_list, r[3]), \
                    'damage':r[4], 'flag':r[5]} for r in result]

            except (sqlite3.DatabaseError) as e:
                raise


class DailyDao(SqliteDao):
    def __init__(self):
        super().__init__(
            table='daily',
            columns='month, date, rank, recordCount, totalScore, totalDamage',
            fields='''
            month INT NOT NULL,
            date TIMESTAMP NOT NULL,
            rank INT NOT NULL,
            recordCount INT NOT NULL,
            totalScore INT NOT NULL,
            totalDamage INT NOT NULL
            ''')

    def add_day_report(self, month, date, rank, recordCount, totalScore, totalDamage, group_id):
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO daily VALUES (?,?,?,?,?,?)", \
                    (month, date, rank, recordCount, totalScore, totalDamage))
                return 1

            except (sqlite3.DatabaseError) as e:
                raise

    def get_day_report(self, date, group_id):
        with self._connect() as conn:
            try:
                result = conn.execute("SELECT * FROM daily WHERE date = ?", (date,)).fetchone()
                if not result:
                    return None
                return {'month': result[0], 'date': result[1], 'rank': result[2], \
                    'recordCount':result[3], 'totalScore':result[4], 'totalDamage':result[5]}

            except (sqlite3.DatabaseError) as e:
                raise

class MemberDao(SqliteDao):
    def __init__(self):
        super().__init__(
            table='member',
            columns='qqid, nickname',
            fields='''
            qqid INT PRIMARY KEY,
            nickname VARCHAR(10) NOT NULL
            ''')

    
    def register(self, qqid, nickname, group_id):
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO member VALUES (?,?)", \
                    (qqid, nickname))
                return 1

            except (sqlite3.DatabaseError) as e:
                raise

    def get_name_from_qq(self, qqid, group_id):
        with self._connect() as conn:
            try:
                result = conn.execute("SELECT nickname FROM member WHERE qqid = ?", \
                    (qqid,)).fetchone()
                if not result:
                    return None
                return result[0]
                

            except (sqlite3.DatabaseError) as e:
                raise

    def get_qq_from_name(self, qqid, group_id):
        with self._connect() as conn:
            try:
                result = conn.execute("SELECT qqid FROM member WHERE nickname = ?", \
                    (qqid,)).fetchone()
                if not result:
                    return None
                return result[0]
                

            except (sqlite3.DatabaseError) as e:
                raise
    
    def update_info(self, qqid, nickname, group_id):
        with self._connect() as conn:
            try:
                conn.execute("UPDATE member SET nickname = ? WHERE qqid = ?", \
                    (nickname, qqid))
                return 1

            except (sqlite3.DatabaseError) as e:
                raise

    def leave(self, qqid, group_id):
        with self._connect() as conn:
            try:
                conn.execute("DELETE FROM member WHERE qqid = ?", \
                    (qqid,))
                return 1

            except (sqlite3.DatabaseError) as e:
                raise
