# scheduler_manager.py

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
import pytz
from datetime import datetime
from croniter import croniter

# 导入我们的任务链执行器和任务注册表
import tasks
import config_manager # 导入配置管理器以读取配置
import constants      # 导入常量以获取时区
import extensions     # 导入 extensions 以获取共享的处理器实例
import task_manager   # 导入 task_manager 以提交任务

logger = logging.getLogger(__name__)

# 自动化任务链
CHAIN_JOB_ID = 'automated_task_chain_job'
# 剧集复活检查
REVIVAL_CHECK_JOB_ID = 'weekly_revival_check_job'

# --- 友好的CRON日志翻译函数】 ---
def _get_next_run_time_str(cron_expression: str) -> str:
    """
    【V3 - 口齿伶俐版】将 CRON 表达式转换为人类可读的、干净的执行计划字符串。
    """
    try:
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError("CRON 表达式必须有5个部分")

        minute, hour, day_of_month, month, day_of_week = parts

        # --- 周期描述 ---
        if minute.startswith('*/') and all(p == '*' for p in [hour, day_of_month, month, day_of_week]):
            return f"每隔 {minute[2:]} 分钟"
        
        if hour.startswith('*/') and all(p == '*' for p in [day_of_month, month, day_of_week]):
            if minute == '0':
                return f"每隔 {hour[2:]} 小时的整点"
            else:
                return f"每隔 {hour[2:]} 小时的第 {minute} 分钟"

        # --- 时间点描述 ---
        time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
        
        if day_of_week != '*':
            day_map = {
                '0': '周日', '1': '周一', '2': '周二', '3': '周三', 
                '4': '周四', '5': '周五', '6': '周六', '7': '周日',
                'sun': '周日', 'mon': '周一', 'tue': '周二', 'wed': '周三',
                'thu': '周四', 'fri': '周五', 'sat': '周六'
            }
            days = [day_map.get(d.lower(), d) for d in day_of_week.split(',')]
            return f"每周的 {','.join(days)} {time_str}"
        
        if day_of_month != '*':
            if day_of_month.startswith('*/'):
                 return f"每隔 {day_of_month[2:]} 天的 {time_str}"
            else:
                 return f"每月的 {day_of_month} 号 {time_str}"

        return f"每天 {time_str}"

    except Exception as e:
        logger.warning(f"无法智能解析CRON表达式 '{cron_expression}': {e}，回退到简单模式。")
        try:
            tz = pytz.timezone(constants.TIMEZONE)
            now = datetime.now(tz)
            iterator = croniter(cron_expression, now)
            next_run = iterator.get_next(datetime)
            return f"下一次将在 {next_run.strftime('%Y-%m-%d %H:%M')}"
        except:
            return f"按计划 '{cron_expression}'"

class SchedulerManager:
    def __init__(self):
        # 从 web_app.py 迁移过来的调度器实例
        self.scheduler = BackgroundScheduler(
            timezone=str(pytz.timezone(constants.TIMEZONE)),
            job_defaults={'misfire_grace_time': 60*5}
        )
        # 获取共享的处理器实例
        self.processor = extensions.media_processor_instance

    def start(self):
        """启动调度器并加载初始任务。"""
        if self.scheduler.running:
            logger.info("定时任务调度器已在运行。")
            return
        try:
            self.scheduler.start()
            logger.info("定时任务调度器已启动。")
            # 在启动时，就根据当前配置更新一次任务
            self.update_task_chain_job()
            self.update_revival_check_job()
        except Exception as e:
            logger.error(f"启动定时任务调度器失败: {e}", exc_info=True)

    def shutdown(self):
        """安全地关闭调度器。"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("定时任务调度器已关闭。")

    # ★★★ 核心修改 4/4: 为复活检查任务创建一个专属的调度函数 ★★★
    def update_revival_check_job(self):
        """
        【新增】根据硬编码的规则，设置每周的剧集复活检查任务。
        """
        if not self.scheduler.running:
            logger.warning("调度器未运行，无法更新'剧集复活检查'任务。")
            return

        logger.trace("正在设置固定的'剧集复活检查'定时任务...")

        try:
            # 1. 同样，先移除旧的作业，防止重复
            self.scheduler.remove_job(REVIVAL_CHECK_JOB_ID)
        except JobLookupError:
            pass # 没找到旧任务是正常的

        # 2. 定义我们的固定调度规则
        cron_str = '0 5 * * sun' # 每周日 (sun) 的 5点 (5) 0分 (0)

        # 3. 从 tasks.py 的注册表里获取任务信息
        registry = tasks.get_task_registry()
        task_info = registry.get('revival-check')
        
        if not task_info:
            logger.error("设置'剧集复活检查'任务失败：在任务注册表中未找到 'revival-check'。")
            return
            
        task_function, task_description, processor_type = task_info

        # 4. 创建一个包装函数，用于提交任务到 task_manager
        def scheduled_revival_check_wrapper():
            logger.info(f"定时任务触发：{task_description}。")
            task_manager.submit_task(
                task_function=task_function,
                task_name=task_description,
                processor_type=processor_type
            )

        # 5. 添加新的作业
        try:
            self.scheduler.add_job(
                func=scheduled_revival_check_wrapper,
                trigger=CronTrigger.from_crontab(cron_str, timezone=str(pytz.timezone(constants.TIMEZONE))),
                id=REVIVAL_CHECK_JOB_ID,
                name=task_description,
                replace_existing=True
            )
            logger.trace(f"已成功设置'{task_description}'任务，执行计划: 每周日 05:00。")
        except ValueError as e:
            logger.error(f"设置'{task_description}'任务失败：CRON表达式 '{cron_str}' 无效。错误: {e}")
    
    def update_task_chain_job(self):
        """
        【核心函数】根据当前配置文件，更新任务链的定时作业。
        这个函数应该在程序启动和每次配置保存后被调用。
        """
        if not self.scheduler.running:
            logger.warning("调度器未运行，无法更新任务。")
            # 即使未运行，也尝试启动它
            self.start()
            if not self.scheduler.running: return

        logger.info("正在根据最新配置更新自动化任务链...")

        try:
            # 1. 无论如何，先尝试移除旧的作业，防止重复或配置残留
            self.scheduler.remove_job(CHAIN_JOB_ID)
            logger.debug(f"已成功移除旧的任务链作业 (ID: {CHAIN_JOB_ID})。")
        except JobLookupError:
            logger.debug(f"没有找到旧的任务链作业 (ID: {CHAIN_JOB_ID})，无需移除。")
        except Exception as e:
            logger.error(f"尝试移除旧任务作业时发生意外错误: {e}", exc_info=True)

        # 2. 读取最新的配置
        config = config_manager.APP_CONFIG
        is_enabled = config.get('task_chain_enabled', False)
        cron_str = config.get('task_chain_cron')
        task_sequence = config.get('task_chain_sequence', [])

        # 3. 如果启用且配置有效，则添加新的作业
        if is_enabled and cron_str and task_sequence:
            try:
                # ★★★ 核心：我们不再直接调用 task_run_chain，而是通过 task_manager 提交 ★★★
                # 这样做可以享受到任务锁、状态更新等所有 task_manager 的好处。
                def scheduled_chain_task_wrapper():
                    logger.info(f"定时任务触发：自动化任务链。")
                    # 注意：这里我们传递 task_sequence 作为参数
                    task_manager.submit_task(
                        tasks.task_run_chain,
                        "自动化任务链",
                        task_sequence=task_sequence
                    )

                self.scheduler.add_job(
                    func=scheduled_chain_task_wrapper, # 调用包装函数
                    trigger=CronTrigger.from_crontab(cron_str, timezone=str(pytz.timezone(constants.TIMEZONE))),
                    id=CHAIN_JOB_ID,
                    name="自动化任务链",
                    replace_existing=True
                )
                # 调用辅助函数来生成友好的日志
                friendly_cron_str = _get_next_run_time_str(cron_str)
                logger.info(f"已成功设置自动化任务链，执行计划: {friendly_cron_str}，包含 {len(task_sequence)} 个任务。")
            except ValueError as e:
                logger.error(f"设置任务链失败：CRON表达式 '{cron_str}' 无效。错误: {e}")
            except Exception as e:
                logger.error(f"添加新的任务链作业时发生未知错误: {e}", exc_info=True)
        else:
            logger.info("自动化任务链未启用或配置不完整，本次不设置定时任务。")

# 创建一个全局单例，方便在其他地方调用
scheduler_manager = SchedulerManager()