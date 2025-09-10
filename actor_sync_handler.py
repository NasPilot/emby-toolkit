# actor_sync_handler.py (最终版)

from typing import Optional
import threading
# 导入必要的模块
import emby_handler
import logging
from db_handler import get_db_connection as get_central_db_connection, get_all_emby_person_ids_from_map, delete_persons_by_emby_ids
from db_handler import ActorDBManager
logger = logging.getLogger(__name__)

class UnifiedSyncHandler:
    def __init__(self, emby_url: str, emby_api_key: str, emby_user_id: Optional[str], tmdb_api_key: str):
        self.actor_db_manager = ActorDBManager()
        self.emby_url = emby_url
        self.emby_api_key = emby_api_key
        self.emby_user_id = emby_user_id
        self.tmdb_api_key = tmdb_api_key # ★★★ 存储TMDb Key，用于记录冲突时获取头像 ★★★
        
        
        logger.trace(f"UnifiedSyncHandler 初始化完成。")
    def sync_emby_person_map_to_db(self, update_status_callback: Optional[callable] = None, stop_event: Optional[threading.Event] = None):
        """
        【V5 - 增加熔断机制】
        在从Emby获取到0条记录时，会先检查数据库现有数据量。
        如果数据库数据量很大，则判定为连接或配置错误，安全中止任务以防止数据丢失。
        """
        logger.trace("开始统一的演员映射表同步任务 (V5 - 安全版)...")
        if update_status_callback: update_status_callback(0, "阶段 1/2: 从 Emby 读取所有演员数据...")

        # ======================================================================
        # 阶段一：从 Emby 读取所有数据到内存
        # ======================================================================
        all_persons_from_emby = []
        try:
            person_generator = emby_handler.get_all_persons_from_emby(self.emby_url, self.emby_api_key, self.emby_user_id, stop_event)
            for person_batch in person_generator:
                if stop_event and stop_event.is_set():
                    logger.warning("任务在读取阶段被用户中止。")
                    if update_status_callback: update_status_callback(-1, "任务已中止")
                    return
                all_persons_from_emby.extend(person_batch)
            
            total_from_emby = len(all_persons_from_emby)
            logger.info(f"  -> Emby 数据读取完成，共获取到 {total_from_emby} 个演员条目。")

        except Exception as e_read:
            logger.error(f"从Emby读取演员数据时发生严重错误: {e_read}", exc_info=True)
            if update_status_callback: update_status_callback(-1, "从Emby读取数据失败")
            return

        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        # ★★★ 核心修改：在这里加入安全检查 (熔断机制) ★★★
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        if total_from_emby == 0:
            logger.warning("从 Emby 获取到 0 个演员条目，正在执行安全检查以防止数据误删...")
            try:
                # 获取当前数据库中的记录总数
                pids_in_db = get_all_emby_person_ids_from_map()
                db_count = len(pids_in_db)
                
                # 设置一个安全阈值，例如100。如果数据库记录超过这个数，就不太可能是空的。
                SAFETY_THRESHOLD = 100 
                
                if db_count > SAFETY_THRESHOLD:
                    # 如果数据库记录很多，但Emby返回0，这绝对是异常情况
                    error_message = f"安全中止：从 Emby 获取到 0 个演员，但数据库中存在 {db_count} 条记录。这极可能是Emby连接配置错误或API失效。为防止数据丢失，同步任务已中止。"
                    logger.error(error_message)
                    if update_status_callback:
                        update_status_callback(-1, "安全中止：无法从Emby获取演员")
                    return # ★★★ 在这里彻底中止函数，后面的代码都不会执行 ★★★
                else:
                    # 如果数据库本身就没多少数据，那么继续执行是安全的
                    logger.info(f"数据库中记录数 ({db_count}) 低于安全阈值，将按预期继续执行清理。")
            except Exception as e_check:
                # 如果连安全检查都失败了，更不能继续
                logger.error(f"执行安全检查时发生数据库错误: {e_check}", exc_info=True)
                if update_status_callback:
                    update_status_callback(-1, "安全检查失败")
                return

        # ======================================================================
        # 阶段二：处理与写入数据库（只有通过安全检查后才会执行）
        # ======================================================================
        stats = { "total": total_from_emby, "processed": 0, "inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0, "errors": 0, "deleted": 0 }
        
        try:
            # ... (后续的所有代码，从 if update_status_callback: ... 到函数结束，都保持原样) ...
            if update_status_callback: update_status_callback(50, "阶段 2/2: 正在同步数据到数据库...")
            
            all_emby_pids_from_sync = {str(p.get("Id", "")).strip() for p in all_persons_from_emby if p.get("Id")}

            with get_central_db_connection() as conn:
                cursor = conn.cursor()
                emby_config_for_upsert = {"url": self.emby_url, "api_key": self.emby_api_key, "user_id": self.emby_user_id}

                # --- 2.1 Upsert 阶段 ---
                for person_emby in all_persons_from_emby:
                    if stop_event and stop_event.is_set():
                        raise InterruptedError("任务在写入阶段被中止")

                    stats["processed"] += 1
                    emby_pid = str(person_emby.get("Id", "")).strip()
                    person_name = str(person_emby.get("Name", "")).strip()

                    if not emby_pid or not person_name:
                        stats["skipped"] += 1
                        continue
                    
                    provider_ids = person_emby.get("ProviderIds", {})
                    person_data_for_db = {
                        "emby_id": emby_pid, "name": person_name,
                        "tmdb_id": provider_ids.get("Tmdb"),
                        "imdb_id": provider_ids.get("Imdb"),
                        "douban_id": provider_ids.get("Douban"),
                    }
                    
                    try:
                        map_id, status = self.actor_db_manager.upsert_person(cursor, person_data_for_db, emby_config=emby_config_for_upsert)
                        if status == "INSERTED": stats['inserted'] += 1
                        elif status == "UPDATED": stats['updated'] += 1
                        elif status == "UNCHANGED": stats['unchanged'] += 1
                        elif status == "SKIPPED": stats['skipped'] += 1
                        else: stats['errors'] += 1
                    except Exception as e_upsert:
                        logger.error(f"同步时写入数据库失败 for EmbyPID {emby_pid}: {e_upsert}")
                        stats['errors'] += 1

                logger.info("  -> 数据写入/更新完成，准备提交事务...")
                conn.commit()

                # --- 2.2 清理阶段 ---
                logger.info("--- 进入清理阶段：移除数据库中多余的演员映射 ---")
                if update_status_callback: update_status_callback(98, "正在对比数据进行清理...")

                pids_in_db = get_all_emby_person_ids_from_map()
                pids_to_delete = list(pids_in_db - all_emby_pids_from_sync)

                if pids_to_delete:
                    logger.warning(f"  -> 发现 {len(pids_to_delete)} 条失效记录需要删除。")
                    deleted_count = delete_persons_by_emby_ids(pids_to_delete)
                    stats['deleted'] = deleted_count
                else:
                    logger.info("  -> 数据库与Emby数据一致，无需清理。")

        except InterruptedError as e:
            logger.warning(str(e))
            if 'conn' in locals() and conn: conn.rollback()
            if update_status_callback: update_status_callback(-1, "任务已中止")
            return
        except Exception as e_write:
            logger.error(f"写入或清理数据库时发生严重错误: {e_write}", exc_info=True)
            if 'conn' in locals() and conn: conn.rollback()
            if update_status_callback: update_status_callback(-1, "数据库操作失败")
            return

        # ... (最终的统计日志输出，保持不变) ...
        total_changed = stats['inserted'] + stats['updated']
        total_failed = stats['skipped'] + stats['errors']

        logger.info("--- 同步演员映射完成 ---")
        logger.info(f"📊 Emby 总数: {stats['total']} 条")
        logger.info(f"⚙️ 已处理: {stats['processed']} 条")
        logger.info(f"✅ 成功写入/更新: {total_changed} 条 (新增: {stats['inserted']}, 更新: {stats['updated']})")
        logger.info(f"➖ 无需变动: {stats['unchanged']} 条")
        logger.info(f"🗑️ 清理失效数据: {stats['deleted']} 条")
        if total_failed > 0:
            logger.warning(f"⚠️ 跳过或错误: {total_failed} 条 (跳过: {stats['skipped']}, 错误: {stats['errors']})")
        logger.info("----------------------")

        if update_status_callback:
            final_message = f"同步完成！新增 {stats['inserted']}，更新 {stats['updated']}，清理 {stats['deleted']}。"
            update_status_callback(100, final_message)

