# tasks.py

import time
import re
import os
import json
import psycopg2
import logging
import threading
from datetime import datetime, date, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed 
import concurrent.futures
import gevent
# 导入类型提示
from typing import Optional, List
from core_processor import MediaProcessor
from watchlist_processor import WatchlistProcessor
from actor_subscription_processor import ActorSubscriptionProcessor
from custom_collection_handler import ListImporter, FilterEngine

# 导入需要的底层模块和共享实例
import db_handler
import emby_handler
import tmdb_handler
import moviepilot_handler
import config_manager
import constants
import extensions
import task_manager
from actor_utils import enrich_all_actor_aliases_task
from actor_sync_handler import UnifiedSyncHandler
from extensions import TASK_REGISTRY
from custom_collection_handler import ListImporter, FilterEngine
from core_processor import _read_local_json
from services.cover_generator import CoverGeneratorService
from utils import get_country_translation_map, translate_country_list

logger = logging.getLogger(__name__)

# ★★★ 全量处理任务 ★★★
def task_run_full_scan(processor: MediaProcessor, force_reprocess: bool = False):
    """
    根据传入的 force_reprocess 参数，决定是执行标准扫描还是强制扫描。
    """
    # 1. 根据参数决定日志信息
    if force_reprocess:
        logger.warning("即将执行【强制】全量处理，将处理所有媒体项...")
    else:
        logger.info("即将执行【标准】全量处理，将跳过已处理项...")


    # 3. 调用核心处理函数，并将 force_reprocess 参数透传下去
    processor.process_full_library(
        update_status_callback=task_manager.update_status_from_thread,
        force_reprocess_all=force_reprocess,
        force_fetch_from_tmdb=force_reprocess
    )

# --- 同步演员映射表 ---
def task_sync_person_map(processor):
    """
    【最终兼容版】任务：同步演员映射表。
    接收 processor 和 is_full_sync 以匹配通用任务执行器，
    但内部逻辑已统一，不再使用 is_full_sync。
    """
    task_name = "同步演员映射"
    # 我们不再需要根据 is_full_sync 来改变任务名了，因为逻辑已经统一
    
    logger.trace(f"开始执行 '{task_name}'...")
    
    try:
        # ★★★ 从传入的 processor 对象中获取 config 字典 ★★★
        config = processor.config
        
        sync_handler = UnifiedSyncHandler(
            emby_url=config.get("emby_server_url"),
            emby_api_key=config.get("emby_api_key"),
            emby_user_id=config.get("emby_user_id"),
            tmdb_api_key=config.get("tmdb_api_key", "")
        )
        
        # 调用同步方法，不再需要传递 is_full_sync
        sync_handler.sync_emby_person_map_to_db(
            update_status_callback=task_manager.update_status_from_thread
        )
        
        logger.trace(f"'{task_name}' 成功完成。")

    except Exception as e:
        logger.error(f"'{task_name}' 执行过程中发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"错误：同步失败 ({str(e)[:50]}...)")
# ✨✨✨ 演员数据补充函数 ✨✨✨
def task_enrich_aliases(processor: MediaProcessor):
    """
    【V3 - 后台任务】演员数据补充任务的入口点。
    - 核心逻辑：内置了30天的固定冷却时间，无需任何外部配置。
    """
    task_name = "演员数据补充"
    logger.info(f"后台任务 '{task_name}' 开始执行...")

    try:
        # 从传入的 processor 对象中获取配置字典
        config = processor.config
        
        # 获取必要的配置项
        tmdb_api_key = config.get(constants.CONFIG_OPTION_TMDB_API_KEY)

        if not tmdb_api_key:
            logger.error(f"任务 '{task_name}' 中止：未在配置中找到 TMDb API Key。")
            task_manager.update_status_from_thread(-1, "错误：缺少TMDb API Key")
            return

        # ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
        # --- 【【【 这 是 核 心 修 改 点 】】】 ---
        
        # 1. 运行时长 (run_duration_minutes)
        # 假设核心函数 enrich_all_actor_aliases_task 仍然需要这个参数。
        # 如果不需要，可以安全地从下面的函数调用中移除它。
        # 我们将其硬编码为 0，代表“不限制时长”，这是最常见的用法。
        duration_minutes = 0

        # 2. 冷却时间 (sync_interval_days)
        # 直接将冷却时间硬编码为 30 天。
        cooldown_days = 30
        
        logger.trace(f"演员数据补充任务将使用固定的 {cooldown_days} 天冷却期。")

        # 调用核心函数，并传递写死的值
        enrich_all_actor_aliases_task(
            tmdb_api_key=tmdb_api_key,
            run_duration_minutes=duration_minutes,
            sync_interval_days=cooldown_days, # <--- 使用我们硬编码的冷却时间
            stop_event=processor.get_stop_event(),
            update_status_callback=task_manager.update_status_from_thread
        )
        # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
        
        logger.info(f"--- '{task_name}' 任务执行完毕。 ---")
        task_manager.update_status_from_thread(100, "演员数据补充任务完成。")

    except Exception as e:
        logger.error(f"'{task_name}' 执行过程中发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"错误：任务失败 ({str(e)[:50]}...)")
# --- 使用手动编辑的结果处理媒体项 ---
def task_manual_update(processor: MediaProcessor, item_id: str, manual_cast_list: list, item_name: str):
    """任务：使用手动编辑的结果处理媒体项"""
    processor.process_item_with_manual_cast(
        item_id=item_id,
        manual_cast_list=manual_cast_list,
        item_name=item_name
    )
# --- 扫描单个演员订阅的所有作品 ---
def task_scan_actor_media(processor: ActorSubscriptionProcessor, subscription_id: int):
    """【新】后台任务：扫描单个演员订阅的所有作品。"""
    logger.trace(f"手动刷新任务(ID: {subscription_id})：开始准备Emby媒体库数据...")
    
    # 在调用核心扫描函数前，必须先获取Emby数据
    emby_tmdb_ids = set()
    try:
        # 从 processor 或全局配置中获取 Emby 连接信息
        config = processor.config # 假设 processor 对象中存有配置
        emby_url = config.get('emby_server_url')
        emby_api_key = config.get('emby_api_key')
        emby_user_id = config.get('emby_user_id')

        all_libraries = emby_handler.get_emby_libraries(emby_url, emby_api_key, emby_user_id)
        library_ids_to_scan = [lib['Id'] for lib in all_libraries if lib.get('CollectionType') in ['movies', 'tvshows']]
        emby_items = emby_handler.get_emby_library_items(base_url=emby_url, api_key=emby_api_key, user_id=emby_user_id, library_ids=library_ids_to_scan, media_type_filter="Movie,Series")
        
        emby_tmdb_ids = {item['ProviderIds'].get('Tmdb') for item in emby_items if item.get('ProviderIds', {}).get('Tmdb')}
        logger.debug(f"手动刷新任务：已从 Emby 获取 {len(emby_tmdb_ids)} 个媒体ID。")

    except Exception as e:
        logger.error(f"手动刷新任务：在获取Emby媒体库信息时失败: {e}", exc_info=True)
        # 获取失败时，可以传递一个空集合，让扫描逻辑继续（但可能不准确），或者直接返回
        # 这里选择继续，让用户至少能更新TMDb信息

    # 现在，带着准备好的 emby_tmdb_ids 调用函数
    processor.run_full_scan_for_actor(subscription_id, emby_tmdb_ids)
# --- 演员订阅 ---
def task_process_actor_subscriptions(processor: ActorSubscriptionProcessor):
    """【新】后台任务：执行所有启用的演员订阅扫描。"""
    processor.run_scheduled_task(update_status_callback=task_manager.update_status_from_thread)
# ★★★ 处理webhook、用于编排任务的函数 ★★★
def webhook_processing_task(processor: MediaProcessor, item_id: str, force_reprocess: bool):
    """
    【V3 - 职责分离最终版】
    编排处理新入库项目的完整流程，所有数据库操作均委托给 db_handler。
    """
    logger.info(f"Webhook 任务启动，处理项目: {item_id}")

    # 步骤 A: 获取完整的项目详情
    item_details = emby_handler.get_emby_item_details(
        item_id, 
        processor.emby_url, 
        processor.emby_api_key, 
        processor.emby_user_id
    )
    if not item_details:
        logger.error(f"Webhook 任务：无法获取项目 {item_id} 的详情，任务中止。")
        return

    # 步骤 B: 调用追剧判断
    processor.check_and_add_to_watchlist(item_details)

    # 步骤 C: 执行通用的元数据处理流程
    processed_successfully = processor.process_single_item(
        item_id, 
        force_reprocess_this_item=force_reprocess 
    )
    
    # --- 步骤 D: 实时合集匹配逻辑 ---
    if not processed_successfully:
        logger.warning(f"  -> 项目 {item_id} 的元数据处理未成功完成，跳过自定义合集匹配。")
        return

    try:
        tmdb_id = item_details.get("ProviderIds", {}).get("Tmdb")
        item_name = item_details.get("Name", f"ID:{item_id}")
        if not tmdb_id:
            logger.debug("  -> 媒体项缺少TMDb ID，无法进行自定义合集匹配。")
            return

        # 1. 从我们的缓存表中获取刚刚存入的元数据
        item_metadata = db_handler.get_media_metadata_by_tmdb_id(tmdb_id)
        if not item_metadata:
            logger.warning(f"无法从本地缓存中找到TMDb ID为 {tmdb_id} 的元数据，无法匹配合集。")
            return

        # --- 2. 匹配 Filter (筛选) 类型的合集 ---
        engine = FilterEngine()
        matching_filter_collections = engine.find_matching_collections(item_metadata)

        if matching_filter_collections:
            logger.info(f"  -> 《{item_name}》匹配到 {len(matching_filter_collections)} 个筛选类合集，正在追加...")
            for collection in matching_filter_collections:
                emby_handler.append_item_to_collection(
                    collection_id=collection['emby_collection_id'],
                    item_emby_id=item_id,
                    base_url=processor.emby_url,
                    api_key=processor.emby_api_key,
                    user_id=processor.emby_user_id
                )
        else:
            logger.info(f"  -> 《{item_name}》没有匹配到任何筛选类合集。")

        # --- 3. 匹配 List (榜单) 类型的合集 ---
        # 调用 db_handler 中的新函数来处理所有数据库逻辑
        updated_list_collections = db_handler.match_and_update_list_collections_on_item_add(
            new_item_tmdb_id=tmdb_id,
            new_item_name=item_name
        )
        
        if updated_list_collections:
            logger.info(f"  -> 《{item_name}》匹配到 {len(updated_list_collections)} 个榜单类合集，正在追加...")
            # 遍历返回的结果，执行 Emby API 调用
            for collection_info in updated_list_collections:
                emby_handler.append_item_to_collection(
                    collection_id=collection_info['emby_collection_id'],
                    item_emby_id=item_id,
                    base_url=processor.emby_url,
                    api_key=processor.emby_api_key,
                    user_id=processor.emby_user_id
                )
        else:
             logger.info(f"  -> 《{item_name}》没有匹配到任何需要更新状态的榜单类合集。")

    except Exception as e:
        logger.error(f"为新入库项目 {item_id} 匹配自定义合集时发生意外错误: {e}", exc_info=True)

    # --- 步骤 E - 为所属的常规媒体库生成封面 ---
    try:
        # (这部分代码无需修改，保持原样即可)
        cover_config_path = os.path.join(config_manager.PERSISTENT_DATA_PATH, "cover_generator.json")
        cover_config = {}
        if os.path.exists(cover_config_path):
            with open(cover_config_path, 'r', encoding='utf-8') as f:
                cover_config = json.load(f)

        if cover_config.get("enabled") and cover_config.get("transfer_monitor"):
            logger.info(f"  -> 检测到 '{item_details.get('Name')}' 入库，将为其所属媒体库生成新封面...")
            
            library_info = emby_handler.get_library_root_for_item(
                item_id, processor.emby_url, processor.emby_api_key, processor.emby_user_id
            )
            
            if not library_info:
                logger.warning(f"  -> 无法为项目 {item_id} 定位到其所属的媒体库根，跳过封面生成。")
                return

            library_id = library_info.get("Id")
            library_name = library_info.get("Name", library_id)
            
            if library_info.get('CollectionType') not in ['movies', 'tvshows', 'boxsets', 'mixed', 'music']:
                logger.debug(f"  -> 父级 '{library_name}' 不是一个常规媒体库，跳过封面生成。")
                return

            server_id = 'main_emby'
            library_unique_id = f"{server_id}-{library_id}"
            if library_unique_id in cover_config.get("exclude_libraries", []):
                logger.info(f"  -> 媒体库 '{library_name}' 在忽略列表中，跳过。")
                return
            
            TYPE_MAP = {
                'movies': 'Movie', 'tvshows': 'Series', 'music': 'MusicAlbum',
                'boxsets': 'BoxSet', 'mixed': 'Movie,Series'
            }
            collection_type = library_info.get('CollectionType')
            item_type_to_query = TYPE_MAP.get(collection_type)
            
            item_count = 0
            if library_id and item_type_to_query:
                item_count = emby_handler.get_item_count(
                    base_url=processor.emby_url,
                    api_key=processor.emby_api_key,
                    user_id=processor.emby_user_id,
                    parent_id=library_id,
                    item_type=item_type_to_query
                ) or 0
            
            logger.info(f"  -> 正在为媒体库 '{library_name}' 生成封面 (当前实时数量: {item_count}) ---")
            cover_service = CoverGeneratorService(config=cover_config)
            cover_service.generate_for_library(
                emby_server_id=server_id,
                library=library_info,
                item_count=item_count 
            )
        else:
            logger.debug("  -> 封面生成器或入库监控未启用，跳过封面生成。")

    except Exception as e:
        logger.error(f"  -> 在新入库后执行精准封面生成时发生错误: {e}", exc_info=True)

    logger.trace(f"  -> Webhook 任务及所有后续流程完成: {item_id}")
# --- 追剧 ---    
def task_process_watchlist(processor: WatchlistProcessor, item_id: Optional[str] = None):
    """
    【V9 - 启动器】
    调用处理器实例来执行追剧任务，并处理UI状态更新。
    """
    # 定义一个可以传递给处理器的回调函数
    def progress_updater(progress, message):
        # 这里的 task_manager.update_status_from_thread 是你项目中用于更新UI的函数
        task_manager.update_status_from_thread(progress, message)

    try:
        # 直接调用 processor 实例的方法，并将回调函数传入
        processor.run_regular_processing_task(progress_callback=progress_updater, item_id=item_id)

    except Exception as e:
        task_name = "追剧列表更新"
        if item_id:
            task_name = f"单项追剧更新 (ID: {item_id})"
        logger.error(f"执行 '{task_name}' 时发生顶层错误: {e}", exc_info=True)
        progress_updater(-1, f"启动任务时发生错误: {e}")
# ★★★ 只更新追剧列表中的一个特定项目 ★★★
def task_refresh_single_watchlist_item(processor: WatchlistProcessor, item_id: str):
    """
    【V11 - 新增】后台任务：只刷新追剧列表中的一个特定项目。
    这是一个职责更明确的函数，专门用于手动触发。
    """
    # 定义一个可以传递给处理器的回调函数
    def progress_updater(progress, message):
        task_manager.update_status_from_thread(progress, message)

    try:
        # 直接调用处理器的主方法，并将 item_id 传入
        # 这会执行完整的元数据刷新、状态检查和数据库更新流程
        processor.run_regular_processing_task(progress_callback=progress_updater, item_id=item_id)

    except Exception as e:
        task_name = f"单项追剧刷新 (ID: {item_id})"
        logger.error(f"执行 '{task_name}' 时发生顶层错误: {e}", exc_info=True)
        progress_updater(-1, f"启动任务时发生错误: {e}")
# ★★★ 执行数据库导入的后台任务 ★★★
def task_import_database(processor, file_content: str, tables_to_import: List[str], import_mode: str):
    """
    【PostgreSQL 安全版 V2】
    从 JSON 文件内容中恢复数据库表。此函数专门处理从 SQLite 备份到 PG 的复杂性。
    - 智能处理数据类型转换。
    - 大量使用 ON CONFLICT (UPSERT) 来安全地合并数据，取代复杂的内存计算。
    - 在事务中运行，保证操作的原子性。
    - 保留了对 translation_cache 的特殊优先级处理逻辑。
    """
    task_name = f"数据库导入 ({import_mode}模式)"
    logger.info(f"后台任务开始：{task_name}，处理表: {tables_to_import}。")
    # task_manager.update_status_from_thread(0, "准备开始导入...") # 假设 task_manager 存在

    # ★ 关键：定义每个表的主键，用于'merge'模式下的 ON CONFLICT
    # 这是从 SQLite 迁移到 PG 最重要的映射之一
    # 注意：对于复合主键，格式是 "col1, col2"
    TABLE_PRIMARY_KEYS = {
        "person_identity_map": "map_id",
        "ActorMetadata": "tmdb_id",
        "translation_cache": "original_text",
        "collections_info": "emby_collection_id",
        "watchlist": "item_id",
        "actor_subscriptions": "id",
        "tracked_actor_media": "id",
        "processed_log": "item_id",
        "failed_log": "item_id",
        "users": "id",
        "custom_collections": "id",
        "media_metadata": "tmdb_id, item_type",
    }
    
    TABLE_TRANSLATIONS = {
        'person_identity_map': '演员映射表', 'ActorMetadata': '演员元数据',
        'translation_cache': '翻译缓存', 'watchlist': '智能追剧列表',
        'actor_subscriptions': '演员订阅配置', 'tracked_actor_media': '已追踪的演员作品',
        'collections_info': '电影合集信息', 'processed_log': '已处理列表',
        'failed_log': '待复核列表', 'users': '用户账户',
        'custom_collections': '自建合集', 'media_metadata': '媒体元数据',
    }

    CLEANING_RULES = {
        'ActorMetadata': {
            'adult': bool  # bool() 函数可以完美地将 0 转为 False, 1 转为 True
        },
        'collections_info': {
            'has_missing': bool
        },
        'watchlist': {
            'force_ended': bool
        }
        # 未来如果发现其他表有类似问题，直接在这里添加规则即可
    }

    summary_lines = []
    conn = None

    try:
        backup = json.loads(file_content)
        backup_data = backup.get("data", {})

        with db_handler.get_db_connection() as conn:
            with conn.cursor() as cursor:
                logger.info("数据库事务已开始。")

                for table_name in tables_to_import:
                    cn_name = TABLE_TRANSLATIONS.get(table_name, table_name)
                    table_data = backup_data.get(table_name, [])

                    if not table_data:
                        logger.debug(f"表 '{cn_name}' 在备份中没有数据，跳过。")
                        summary_lines.append(f"  - 表 '{cn_name}': 跳过 (备份中无数据)。")
                        continue
                    
                    logger.info(f"正在处理表: '{cn_name}'，共 {len(table_data)} 行。")

                    # --- 模式1：覆盖模式 ---
                    if import_mode == 'overwrite':
                        logger.warning(f"执行覆盖模式：将清空表 '{table_name}' 中的所有数据！")
                        # TRUNCATE ... RESTART IDENTITY 会重置自增ID，CASCADE 会处理外键依赖
                        cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;")
                        
                        
                        # 清空后直接批量插入
                        all_cols = list(table_data[0].keys())
                        # 过滤掉自增主键，让数据库自己生成
                        cols_to_insert = [c for c in all_cols if c not in ['id', 'map_id']]
                        data_to_insert = []
                        table_rules = CLEANING_RULES.get(table_name, {})
                        for row in table_data:
                            cleaned_row_values = []
                            for col_name in cols_to_insert:
                                value = row.get(col_name)
                                # 如果当前列有清洗规则，就应用它
                                if col_name in table_rules:
                                    value = table_rules[col_name](value) if value is not None else None
                                cleaned_row_values.append(value)
                            data_to_insert.append(cleaned_row_values)
                        col_str = ", ".join(cols_to_insert)
                        val_ph = ", ".join(["%s"] * len(cols_to_insert))
                        sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({val_ph})"
                        
                        data_to_insert = [[row.get(c) for c in cols_to_insert] for row in table_data]
                        cursor.executemany(sql, data_to_insert)
                        summary_lines.append(f"  - 表 '{cn_name}': 清空并插入 {len(data_to_insert)} 条。")
                        continue # 处理完这个表，进入下一个循环

                    # --- 模式2：合并模式 ---
                    
                    # ★ 特殊处理 translation_cache 的优先级合并逻辑 ★
                    if table_name == 'translation_cache':
                        logger.info(f"模式[共享合并]: 正在为 '{cn_name}' 表执行基于优先级的合并策略...")
                        TRANSLATION_SOURCE_PRIORITY = {'manual': 2, 'openai': 1, 'zhipuai': 1, 'gemini': 1}
                        
                        cursor.execute("SELECT original_text, translated_text, engine_used FROM translation_cache")
                        local_cache = {row['original_text']: row for row in cursor.fetchall()}
                        
                        rows_to_upsert = []
                        kept_count = 0
                        
                        for backup_row in table_data:
                            key = backup_row.get('original_text')
                            if not key: continue
                            
                            local_row = local_cache.get(key)
                            if not local_row:
                                rows_to_upsert.append(backup_row)
                                continue

                            local_priority = TRANSLATION_SOURCE_PRIORITY.get(local_row.get('engine_used'), 0)
                            backup_priority = TRANSLATION_SOURCE_PRIORITY.get(backup_row.get('engine_used'), 0)

                            if backup_priority > local_priority:
                                rows_to_upsert.append(backup_row)
                            else:
                                kept_count += 1
                        
                        if rows_to_upsert:
                            cols = list(rows_to_upsert[0].keys())
                            col_str = ", ".join(cols)
                            val_ph = ", ".join(["%s"] * len(cols))
                            update_str = ", ".join([f"{col} = EXCLUDED.{col}" for col in cols if col != 'original_text'])
                            
                            sql = f"""
                                INSERT INTO translation_cache ({col_str}) VALUES ({val_ph})
                                ON CONFLICT (original_text) DO UPDATE SET {update_str}
                            """
                            data = [[row.get(c) for c in cols] for row in rows_to_upsert]
                            cursor.executemany(sql, data)

                        summary_lines.append(f"  - 表 '{cn_name}': 合并/更新 {len(rows_to_upsert)} 条, 保留本地更优 {kept_count} 条。")

                    # ★ 通用合并逻辑 (适用于包括 person_identity_map 在内的所有其他表) ★
                    else:
                        pk = TABLE_PRIMARY_KEYS.get(table_name)
                        if not pk:
                            logger.warning(f"表 '{cn_name}' 未定义主键，无法执行合并，已跳过。")
                            summary_lines.append(f"  - 表 '{cn_name}': 跳过 (未定义合并键)。")
                            continue

                        all_cols = list(table_data[0].keys())
                        # 在合并模式下，我们信任备份文件中的主键ID
                        col_str = ", ".join(all_cols)
                        val_ph = ", ".join(["%s"] * len(all_cols))
                        
                        # 主键列（们）
                        pk_cols = [p.strip() for p in pk.split(',')]
                        # 需要在冲突时更新的列（除了主键之外的所有列）
                        update_cols = [c for c in all_cols if c not in pk_cols]
                        update_str = ", ".join([f"{col} = EXCLUDED.{col}" for col in update_cols])

                        # 构建强大的 UPSERT 语句
                        sql = f"""
                            INSERT INTO {table_name} ({col_str}) VALUES ({val_ph})
                            ON CONFLICT ({pk}) DO UPDATE SET {update_str}
                        """
                        
                        data_to_upsert = [[row.get(c) for c in all_cols] for row in table_data]
                        data_to_upsert = []
                        table_rules = CLEANING_RULES.get(table_name, {})
                        for row in table_data:
                            cleaned_row_values = []
                            for col_name in all_cols: # 注意这里用 all_cols
                                value = row.get(col_name)
                                # 如果当前列有清洗规则，就应用它
                                if col_name in table_rules:
                                    value = table_rules[col_name](value) if value is not None else None
                                cleaned_row_values.append(value)
                            data_to_upsert.append(cleaned_row_values)
                        cursor.executemany(sql, data_to_upsert)
                        summary_lines.append(f"  - 表 '{cn_name}': 安全合并/更新了 {len(data_to_upsert)} 条记录。")

                # --- 循环结束，打印最终摘要 ---
                logger.info("="*11 + " 数据库导入摘要 " + "="*11)
                for line in summary_lines: logger.info(line)
                logger.info("="*36)

                conn.commit()
                logger.info("✅ 数据库事务已成功提交！所有选择的表已恢复。")
                # task_manager.update_status_from_thread(100, "导入成功完成！")

    except Exception as e:
        logger.error(f"数据库导入任务发生严重错误，所有更改将回滚: {e}", exc_info=True)
        if conn:
            conn.rollback()
# ★★★ 重新处理单个项目 ★★★
def task_reprocess_single_item(processor: MediaProcessor, item_id: str, item_name_for_ui: str):
    """
    【最终版 - 职责分离】后台任务。
    此版本负责在任务开始时设置“正在处理”的状态，并执行核心逻辑。
    """
    logger.debug(f"--- 后台任务开始执行 ({item_name_for_ui}) ---")
    
    try:
        # ✨ 关键修改：任务一开始，就用“正在处理”的状态覆盖掉旧状态
        task_manager.update_status_from_thread(0, f"正在处理: {item_name_for_ui}")

        # 现在才开始真正的工作
        processor.process_single_item(
            item_id, 
            force_reprocess_this_item=True,
            force_fetch_from_tmdb=True
        )
        # 任务成功完成后的状态更新会自动由任务队列处理，我们无需关心
        logger.debug(f"--- 后台任务完成 ({item_name_for_ui}) ---")

    except Exception as e:
        logger.error(f"后台任务处理 '{item_name_for_ui}' 时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"处理失败: {item_name_for_ui}")
# --- 翻译演员任务 ---
def task_actor_translation_cleanup(processor):
    """
    【最终修正版】执行演员名翻译的查漏补缺工作，并使用正确的全局状态更新函数。
    """
    try:
        # ✨✨✨ 修正：直接调用全局函数，而不是processor的方法 ✨✨✨
        task_manager.update_status_from_thread(5, "正在准备需要翻译的演员数据...")
        
        # 1. 调用数据准备函数
        translation_map, name_to_persons_map = emby_handler.prepare_actor_translation_data(
            emby_url=processor.emby_url,
            emby_api_key=processor.emby_api_key,
            user_id=processor.emby_user_id,
            ai_translator=processor.ai_translator,
            stop_event=processor.get_stop_event()
        )

        if not translation_map:
            task_manager.update_status_from_thread(100, "任务完成，没有需要翻译的演员。")
            return

        total_to_update = len(translation_map)
        task_manager.update_status_from_thread(50, f"数据准备完毕，开始更新 {total_to_update} 个演员名...")
        
        update_count = 0
        processed_count = 0

        # 2. 主循环
        for original_name, translated_name in translation_map.items():
            processed_count += 1
            if processor.is_stop_requested():
                logger.info("演员翻译任务被用户中断。")
                break
            
            if not translated_name or original_name == translated_name:
                continue

            persons_to_update = name_to_persons_map.get(original_name, [])
            for person in persons_to_update:
                # 3. 更新单个条目
                success = emby_handler.update_person_details(
                    person_id=person.get("Id"),
                    new_data={"Name": translated_name},
                    emby_server_url=processor.emby_url,
                    emby_api_key=processor.emby_api_key,
                    user_id=processor.emby_user_id
                )
                if success:
                    update_count += 1
                    time.sleep(0.2)

            # 4. 更新进度
            progress = int(50 + (processed_count / total_to_update) * 50)
            task_manager.update_status_from_thread(progress, f"({processed_count}/{total_to_update}) 正在更新: {original_name} -> {translated_name}")

        # 任务结束时，也直接调用全局函数
        final_message = f"任务完成！共更新了 {update_count} 个演员名。"
        if processor.is_stop_requested():
            final_message = "任务已中断。"
        task_manager.update_status_from_thread(100, final_message)

    except Exception as e:
        logger.error(f"执行演员翻译任务时出错: {e}", exc_info=True)
        # 在异常处理中也直接调用全局函数
        task_manager.update_status_from_thread(-1, f"任务失败: {e}")
# ★★★ 重新处理所有待复核项 ★★★
def task_reprocess_all_review_items(processor: MediaProcessor):
    """
    【已升级】后台任务：遍历所有待复核项并逐一以“强制在线获取”模式重新处理。
    """
    logger.trace("--- 开始执行“重新处理所有待复核项”任务 [强制在线获取模式] ---")
    try:
        # +++ 核心修改 1：同时查询 item_id 和 item_name +++
        with db_handler.get_db_connection() as conn:
            cursor = conn.cursor()
            # 从 failed_log 中同时获取 ID 和 Name
            cursor.execute("SELECT item_id, item_name FROM failed_log")
            # 将结果保存为一个字典列表，方便后续使用
            all_items = [{'id': row['item_id'], 'name': row['item_name']} for row in cursor.fetchall()]
        
        total = len(all_items)
        if total == 0:
            logger.info("待复核列表中没有项目，任务结束。")
            task_manager.update_status_from_thread(100, "待复核列表为空。")
            return

        logger.info(f"共找到 {total} 个待复核项需要以“强制在线获取”模式重新处理。")

        # +++ 核心修改 2：在循环中解包 item_id 和 item_name +++
        for i, item in enumerate(all_items):
            if processor.is_stop_requested():
                logger.info("任务被中止。")
                break
            
            item_id = item['id']
            item_name = item['name'] or f"ItemID: {item_id}" # 如果名字为空，提供一个备用名

            task_manager.update_status_from_thread(int((i/total)*100), f"正在重新处理 {i+1}/{total}: {item_name}")
            
            # +++ 核心修改 3：传递所有必需的参数 +++
            task_reprocess_single_item(processor, item_id, item_name)
            
            # 每个项目之间稍作停顿
            time.sleep(2) 

    except Exception as e:
        logger.error(f"重新处理所有待复核项时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, "任务失败")
# ★★★ 同步覆盖缓存的任务函数 ★★★
def task_full_image_sync(processor: MediaProcessor, force_full_update: bool = False):
    """
    后台任务：调用 processor 的方法来同步所有图片。
    新增 force_full_update 参数以支持深度模式。
    """
    # 直接把回调函数和新参数传进去
    processor.sync_all_media_assets(
        update_status_callback=task_manager.update_status_from_thread,
        force_full_update=force_full_update
    )
# ✨ 辅助函数，并发刷新合集使用
def _process_single_collection_concurrently(collection_data: dict, tmdb_api_key: str) -> dict:
    """
    【V4 - 纯粹电影版】
    在单个线程中处理单个电影合集的所有逻辑。
    这个函数现在可以完全信任传入的 collection_data 就是一个常规电影合集。
    """
    collection_id = collection_data['Id']
    collection_name = collection_data.get('Name', '')
    today_str = datetime.now().strftime('%Y-%m-%d')
    item_type = 'Movie'
    
    all_movies_with_status = []
    emby_movie_tmdb_ids = set(collection_data.get("ExistingMovieTmdbIds", []))
    in_library_count = len(emby_movie_tmdb_ids)
    status, has_missing = "ok", False
    provider_ids = collection_data.get("ProviderIds", {})
    
    tmdb_id = provider_ids.get("TmdbCollection") or provider_ids.get("TmdbCollectionId") or provider_ids.get("Tmdb")

    if not tmdb_id:
        status = "unlinked"
    else:
        details = tmdb_handler.get_collection_details_tmdb(int(tmdb_id), tmdb_api_key)
        if not details or "parts" not in details:
            status = "tmdb_error"
        else:
            with db_handler.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT missing_movies_json FROM collections_info WHERE emby_collection_id = %s", (collection_id,))
                row = cursor.fetchone()
                previous_movies_map = {}
                if row and row[0]:
                    try:
                        previous_movies_map = {str(m['tmdb_id']): m for m in json.loads(row[0])}
                    except (json.JSONDecodeError, TypeError): pass
            
            for movie in details.get("parts", []):
                movie_tmdb_id = str(movie.get("id"))
                if not movie.get("release_date"): continue

                movie_status = "unknown"
                if movie_tmdb_id in emby_movie_tmdb_ids:
                    movie_status = "in_library"
                elif movie.get("release_date", '') > today_str:
                    movie_status = "unreleased"
                elif previous_movies_map.get(movie_tmdb_id, {}).get('status') == 'subscribed':
                    movie_status = "subscribed"
                else:
                    movie_status = "missing"

                all_movies_with_status.append({
                    "tmdb_id": movie_tmdb_id, "title": movie.get("title", ""), 
                    "release_date": movie.get("release_date"), "poster_path": movie.get("poster_path"), 
                    "status": movie_status
                })
            
            if any(m['status'] == 'missing' for m in all_movies_with_status):
                has_missing = True
                status = "has_missing"

    image_tag = collection_data.get("ImageTags", {}).get("Primary")
    poster_path = f"/Items/{collection_id}/Images/Primary%stag={image_tag}" if image_tag else None

    return {
        "emby_collection_id": collection_id, "name": collection_name, 
        "tmdb_collection_id": tmdb_id, "item_type": item_type,
        "status": status, "has_missing": has_missing, 
        "missing_movies_json": json.dumps(all_movies_with_status), 
        "last_checked_at": time.time(), "poster_path": poster_path, 
        "in_library_count": in_library_count
    }
# ★★★ 刷新合集的后台任务函数 ★★★
def task_refresh_collections(processor: MediaProcessor):
    """
    【V2 - PG语法修正版】
    - 修复了数据库批量写入时使用 SQLite 特有语法 INSERT OR REPLACE 的问题。
    - 改为使用 PostgreSQL 标准的 ON CONFLICT ... DO UPDATE 语法，确保数据能被正确地插入或更新。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    task_manager.update_status_from_thread(0, "正在获取 Emby 合集列表...")
    try:
        emby_collections = emby_handler.get_all_collections_with_items(
            base_url=processor.emby_url, api_key=processor.emby_api_key, user_id=processor.emby_user_id
        )
        if emby_collections is None: raise RuntimeError("从 Emby 获取合集列表失败")

        total = len(emby_collections)
        task_manager.update_status_from_thread(5, f"共找到 {total} 个合集，准备开始并发处理...")

        # 清理数据库中已不存在的合集
        with db_handler.get_db_connection() as conn:
            cursor = conn.cursor()
            emby_current_ids = {c['Id'] for c in emby_collections}
            # ★★★ 语法修正：PostgreSQL 的 cursor.fetchall() 返回字典列表，需要正确提取 ★★★
            cursor.execute("SELECT emby_collection_id FROM collections_info")
            db_known_ids = {row['emby_collection_id'] for row in cursor.fetchall()}
            deleted_ids = db_known_ids - emby_current_ids
            if deleted_ids:
                # executemany 需要一个元组列表
                cursor.executemany("DELETE FROM collections_info WHERE emby_collection_id = %s", [(id,) for id in deleted_ids])
            conn.commit()

        tmdb_api_key = config_manager.APP_CONFIG.get(constants.CONFIG_OPTION_TMDB_API_KEY)
        if not tmdb_api_key: raise RuntimeError("未配置 TMDb API Key")

        processed_count = 0
        all_results = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_process_single_collection_concurrently, collection, tmdb_api_key): collection for collection in emby_collections}
            
            for future in as_completed(futures):
                if processor.is_stop_requested():
                    for f in futures: f.cancel()
                    break
                
                collection_name = futures[future].get('Name', '未知合集')
                try:
                    result = future.result()
                    all_results.append(result)
                except Exception as e:
                    logger.error(f"处理合集 '{collection_name}' 时线程内发生错误: {e}", exc_info=True)
                
                processed_count += 1
                progress = 10 + int((processed_count / total) * 90)
                task_manager.update_status_from_thread(progress, f"处理中: {collection_name[:20]}... ({processed_count}/{total})")

        if processor.is_stop_requested():
            logger.warning("任务被用户中断，部分数据可能未被处理。")
        
        if all_results:
            logger.info(f"并发处理完成，准备将 {len(all_results)} 条结果写入数据库...")
            with db_handler.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION;")
                try:
                    # ★★★ 核心修复：将 INSERT OR REPLACE 改为 ON CONFLICT ... DO UPDATE ★★★
                    # 1. 定义所有列和占位符
                    cols = all_results[0].keys()
                    cols_str = ", ".join(cols)
                    placeholders_str = ", ".join([f"%({k})s" for k in cols]) # 使用 %(key)s 格式
                    
                    # 2. 定义冲突时的更新规则
                    update_cols = [f"{col} = EXCLUDED.{col}" for col in cols if col != 'emby_collection_id']
                    update_str = ", ".join(update_cols)
                    
                    # 3. 构建最终的SQL
                    sql = f"""
                        INSERT INTO collections_info ({cols_str})
                        VALUES ({placeholders_str})
                        ON CONFLICT (emby_collection_id) DO UPDATE SET {update_str}
                    """
                    
                    # 4. 使用 executemany 执行
                    cursor.executemany(sql, all_results)
                    conn.commit()
                    logger.info("数据库写入成功！")
                except Exception as e_db:
                    logger.error(f"数据库批量写入时发生错误: {e_db}", exc_info=True)
                    conn.rollback()
        
    except Exception as e:
        logger.error(f"刷新合集任务失败: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"错误: {e}")
# ★★★ 带智能预判的自动订阅任务 ★★★
def task_auto_subscribe(processor: MediaProcessor):
    """
    【V5 - 最终完整版】
    全面覆盖原生电影合集、自定义电影合集、自定义剧集合集，并统一使用 'subscribed' 状态。
    """
    task_manager.update_status_from_thread(0, "正在启动智能订阅任务...")
    
    if not config_manager.APP_CONFIG.get(constants.CONFIG_OPTION_AUTOSUB_ENABLED):
        logger.info("智能订阅总开关未开启，任务跳过。")
        task_manager.update_status_from_thread(100, "任务跳过：总开关未开启")
        return

    try:
        today = date.today()
        task_manager.update_status_from_thread(10, "智能订阅已启动...")
        successfully_subscribed_items = []

        with db_handler.get_db_connection() as conn:
            cursor = conn.cursor()

            # ★★★ 1. 处理原生电影合集 (collections_info) ★★★
            if not processor.is_stop_requested():
                task_manager.update_status_from_thread(20, "正在检查原生电影合集...")
                sql_query_native_movies = "SELECT * FROM collections_info WHERE status = 'has_missing' AND missing_movies_json IS NOT NULL AND missing_movies_json != '[]'"
                cursor.execute(sql_query_native_movies)
                native_collections_to_check = cursor.fetchall()
                logger.info(f"  -> 找到 {len(native_collections_to_check)} 个有缺失影片的原生合集。")

                for collection in native_collections_to_check:
                    if processor.is_stop_requested(): break
                    
                    movies_to_keep = []
                    all_movies = json.loads(collection['missing_movies_json'])
                    movies_changed = False
                    
                    for movie in all_movies:
                        if processor.is_stop_requested(): break
                        if movie.get('status') == 'missing':
                            release_date_str = movie.get('release_date')
                            if not release_date_str:
                                movies_to_keep.append(movie)
                                continue
                            try:
                                release_date = datetime.strptime(release_date_str.strip(), '%Y-%m-%d').date()
                            except (ValueError, TypeError):
                                movies_to_keep.append(movie)
                                continue
                            
                            if release_date <= today:
                                if moviepilot_handler.subscribe_movie_to_moviepilot(movie, config_manager.APP_CONFIG):
                                    successfully_subscribed_items.append(f"电影《{movie['title']}》")
                                    movies_changed = True
                                    movie['status'] = 'subscribed'
                                    movies_to_keep.append(movie)
                                else:
                                    movies_to_keep.append(movie)
                            else:
                                movies_to_keep.append(movie)
                        else:
                            movies_to_keep.append(movie)
                            
                    if movies_changed:
                        new_missing_json = json.dumps(movies_to_keep)
                        new_status = 'ok' if not any(m.get('status') == 'missing' for m in movies_to_keep) else 'has_missing'
                        cursor.execute("UPDATE collections_info SET missing_movies_json = %s, status = %s WHERE emby_collection_id = %s", (new_missing_json, new_status, collection['emby_collection_id']))

            # --- 2. 处理智能追剧 ---
            if not processor.is_stop_requested():
                task_manager.update_status_from_thread(60, "正在检查缺失的剧集...")
                
                sql_query = "SELECT * FROM watchlist WHERE status IN ('Watching', 'Paused') AND missing_info_json IS NOT NULL AND missing_info_json != '[]'"
                logger.debug(f"  -> 剧集 执行查询: {sql_query}")
                cursor.execute(sql_query)
                series_to_check = cursor.fetchall()
                
                logger.trace(f"【智能订阅-剧集】从数据库找到 {len(series_to_check)} 部状态为'在追'或'暂停'且有缺失信息的剧集需要检查。")

                for series in series_to_check:
                    if processor.is_stop_requested(): break
                    
                    series_name = series['item_name']
                    logger.info(f"  -> 正在检查: 《{series_name}》")
                    
                    try:
                        missing_info = json.loads(series['missing_info_json'])
                        missing_seasons = missing_info.get('missing_seasons', [])
                        
                        if not missing_seasons:
                            logger.info(f"  -> 《{series_name}》没有记录在案的缺失季(missing_seasons为空)，跳过。")
                            continue

                        seasons_to_keep = []
                        seasons_changed = False
                        for season in missing_seasons:
                            if processor.is_stop_requested(): break
                            
                            season_num = season.get('season_number')
                            air_date_str = season.get('air_date')
                            if air_date_str:
                                air_date_str = air_date_str.strip()
                            
                            if not air_date_str:
                                logger.warning(f"  -> 《{series_name}》第 {season_num} 季缺少播出日期(air_date)，无法判断，跳过。")
                                seasons_to_keep.append(season)
                                continue
                            
                            try:
                                season_date = datetime.strptime(air_date_str, '%Y-%m-%d').date()
                            except (ValueError, TypeError):
                                logger.warning(f"  -> 《{series_name}》第 {season_num} 季的播出日期 '{air_date_str}' 格式无效，跳过。")
                                seasons_to_keep.append(season)
                                continue

                            if season_date <= today:
                                logger.info(f"  -> 《{series_name}》第 {season_num} 季 (播出日期: {season_date}) 已播出，符合订阅条件，正在提交...")
                                try:
                                    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
                                    # ★★★  核心修复：剧集订阅也需要传递 config_manager.APP_CONFIG！ ★★★
                                    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
                                    success = moviepilot_handler.subscribe_series_to_moviepilot(dict(series), season['season_number'], config_manager.APP_CONFIG)
                                    if success:
                                        logger.info(f"  -> ✅ 订阅成功！")
                                        successfully_subscribed_items.append(f"《{series['item_name']}》第 {season['season_number']} 季")
                                        seasons_changed = True
                                    else:
                                        logger.error(f"  -> MoviePilot报告订阅失败！将保留在缺失列表中。")
                                        seasons_to_keep.append(season)
                                except Exception as e:
                                    logger.error(f"【智能订阅-剧集】      -> 提交订阅到MoviePilot时发生内部错误: {e}", exc_info=True)
                                    seasons_to_keep.append(season)
                            else:
                                logger.info(f"  -> 《{series_name}》第 {season_num} 季 (播出日期: {season_date}) 尚未播出，跳过订阅。")
                                seasons_to_keep.append(season)
                        
                        if seasons_changed:
                            missing_info['missing_seasons'] = seasons_to_keep
                            cursor.execute("UPDATE watchlist SET missing_info_json = %s WHERE item_id = %s", (json.dumps(missing_info), series['item_id']))
                    except Exception as e_series:
                        logger.error(f"【智能订阅-剧集】处理剧集 '{series['item_name']}' 时出错: {e_series}")

            # ★★★ 3. 处理自定义合集 (custom_collections, item_type='Movie') ★★★
            if not processor.is_stop_requested():
                task_manager.update_status_from_thread(70, "正在检查自定义榜单合集...")
                
                # 步骤 1: 使用统一的SQL查询，获取所有需要处理的榜单
                sql_query_custom_collections = """
                    SELECT * FROM custom_collections 
                    WHERE type = 'list' AND health_status = 'has_missing' 
                    AND generated_media_info_json IS NOT NULL AND generated_media_info_json != '[]'
                """
                cursor.execute(sql_query_custom_collections)
                custom_collections_to_check = cursor.fetchall()
                logger.info(f"  -> 找到 {len(custom_collections_to_check)} 个有缺失媒体的自定义榜单。")

                # 步骤 2: 统一循环处理
                for collection in custom_collections_to_check:
                    if processor.is_stop_requested(): break
                    
                    collection_id = collection['id']
                    collection_name = collection['name']
                    
                    try:
                        # 步骤 2a: ★★★ 移植“防御性解析”逻辑，获取权威类型 ★★★
                        definition = json.loads(collection['definition_json'])
                        item_type_from_db = definition.get('item_type', 'Movie')

                        authoritative_type = None
                        if isinstance(item_type_from_db, list) and item_type_from_db:
                            authoritative_type = item_type_from_db[0] # 规则：取列表中的第一个作为该榜单的主要类型
                        elif isinstance(item_type_from_db, str):
                            authoritative_type = item_type_from_db
                        
                        if authoritative_type not in ['Movie', 'Series']:
                            logger.warning(f"  -> 合集 '{collection_name}' 的 item_type ('{authoritative_type}') 无法识别，将默认按 'Movie' 处理。")
                            authoritative_type = 'Movie'

                        # 步骤 2b: 遍历媒体列表，执行订阅
                        media_to_keep = []
                        all_media = json.loads(collection['generated_media_info_json'])
                        media_changed = False
                        
                        for media_item in all_media:
                            if processor.is_stop_requested(): break
                            
                            if media_item.get('status') == 'missing':
                                release_date_str = media_item.get('release_date')
                                if not release_date_str:
                                    media_to_keep.append(media_item)
                                    continue
                                try:
                                    release_date = datetime.strptime(release_date_str.strip(), '%Y-%m-%d').date()
                                except (ValueError, TypeError):
                                    media_to_keep.append(media_item)
                                    continue
                                
                                if release_date <= today:
                                    # ★★★ 使用权威类型来决定调用哪个订阅函数 ★★★
                                    success = False
                                    media_title = media_item.get('title', '未知标题')
                                    if authoritative_type == 'Movie':
                                        success = moviepilot_handler.subscribe_movie_to_moviepilot(media_item, config_manager.APP_CONFIG)
                                    elif authoritative_type == 'Series':
                                        series_info = { "item_name": media_title, "tmdb_id": media_item.get('tmdb_id') }
                                        success = moviepilot_handler.subscribe_series_to_moviepilot(series_info, season_number=None, config=config_manager.APP_CONFIG)
                                    
                                    if success:
                                        successfully_subscribed_items.append(f"{authoritative_type}《{media_title}》")
                                        media_changed = True
                                        media_item['status'] = 'subscribed'
                                        media_to_keep.append(media_item)
                                    else:
                                        media_to_keep.append(media_item)
                                else:
                                    media_to_keep.append(media_item)
                            else:
                                media_to_keep.append(media_item)
                        
                        # 步骤 2c: 如果有订阅成功，更新数据库
                        if media_changed:
                            new_missing_json = json.dumps(media_to_keep, ensure_ascii=False)
                            new_missing_count = sum(1 for m in media_to_keep if m.get('status') == 'missing')
                            new_health_status = 'has_missing' if new_missing_count > 0 else 'ok'
                            cursor.execute(
                                "UPDATE custom_collections SET generated_media_info_json = %s, health_status = %s, missing_count = %s WHERE id = %s", 
                                (new_missing_json, new_health_status, new_missing_count, collection_id)
                            )
                    except Exception as e_coll:
                        logger.error(f"  -> 处理自定义合集 '{collection_name}' 时发生错误: {e_coll}", exc_info=True)

            conn.commit()

        if successfully_subscribed_items:
            summary = "  -> ✅ 任务完成！已自动订阅: " + ", ".join(successfully_subscribed_items)
            logger.info(summary)
            task_manager.update_status_from_thread(100, summary)
        else:
            task_manager.update_status_from_thread(100, "任务完成：本次运行没有发现符合自动订阅条件的媒体。")

    except Exception as e:
        logger.error(f"智能订阅任务失败: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"错误: {e}")
# ✨✨✨ 一键添加所有剧集到追剧列表的任务 ✨✨✨
def task_add_all_series_to_watchlist(processor: MediaProcessor):
    """
    【V2 - PG语法修正版】
    - 修复了数据库写入时使用 SQLite 特有语法 INSERT OR IGNORE 和 ? 占位符的问题。
    - 改为使用 PostgreSQL 标准的 ON CONFLICT ... DO NOTHING 语法。
    """
    task_name = "一键扫描全库剧集"
    logger.trace(f"--- 开始执行 '{task_name}' 任务 ---")
    
    try:
        emby_url = processor.emby_url
        emby_api_key = processor.emby_api_key
        emby_user_id = processor.emby_user_id
        
        library_ids_to_process = config_manager.APP_CONFIG.get('emby_libraries_to_process', [])
        
        if not library_ids_to_process:
            logger.info("未在配置中指定媒体库，将自动扫描所有媒体库...")
            all_libraries = emby_handler.get_emby_libraries(emby_url, emby_api_key, emby_user_id)
            if all_libraries:
                library_ids_to_process = [
                    lib['Id'] for lib in all_libraries 
                    if lib.get('CollectionType') in ['tvshows', 'mixed']
                ]
                logger.info(f"将扫描以下剧集库: {[lib['Name'] for lib in all_libraries if lib.get('CollectionType') in ['tvshows', 'mixed']]}")
            else:
                logger.warning("未能从 Emby 获取到任何媒体库。")
        
        if not library_ids_to_process:
            task_manager.update_status_from_thread(100, "任务完成：没有找到可供扫描的剧集媒体库。")
            return

        task_manager.update_status_from_thread(10, "正在从 Emby 获取所有剧集...")
        all_series = emby_handler.get_emby_library_items(
            base_url=emby_url,
            api_key=emby_api_key,
            user_id=emby_user_id,
            library_ids=library_ids_to_process,
            media_type_filter="Series"
        )

        if all_series is None:
            raise RuntimeError("从 Emby 获取剧集列表失败，请检查网络和配置。")

        total = len(all_series)
        if total == 0:
            task_manager.update_status_from_thread(100, "任务完成：在指定的媒体库中未找到任何剧集。")
            return

        task_manager.update_status_from_thread(30, f"共找到 {total} 部剧集，正在筛选...")
        series_to_insert = []
        for series in all_series:
            tmdb_id = series.get("ProviderIds", {}).get("Tmdb")
            item_name = series.get("Name")
            item_id = series.get("Id")
            if tmdb_id and item_name and item_id:
                series_to_insert.append({
                    "item_id": item_id, "tmdb_id": tmdb_id,
                    "item_name": item_name, "item_type": "Series"
                })

        if not series_to_insert:
            task_manager.update_status_from_thread(100, "任务完成：找到的剧集均缺少TMDb ID，无法添加。")
            return

        added_count = 0
        total_to_add = len(series_to_insert)
        task_manager.update_status_from_thread(60, f"筛选出 {total_to_add} 部有效剧集，准备写入数据库...")
        
        with db_handler.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION;")
            try:
                for series in series_to_insert:
                    # ★★★ 核心修复：将 INSERT OR IGNORE 和 ? 改为 ON CONFLICT 和 %s ★★★
                    cursor.execute("""
                        INSERT INTO watchlist (item_id, tmdb_id, item_name, item_type, status)
                        VALUES (%s, %s, %s, %s, 'Watching')
                        ON CONFLICT (item_id) DO NOTHING
                    """, (series["item_id"], series["tmdb_id"], series["item_name"], series["item_type"]))
                    # cursor.rowcount 在 ON CONFLICT DO NOTHING 时，如果发生冲突，可能返回0，但插入成功时返回1
                    if cursor.rowcount > 0:
                        added_count += 1
                conn.commit()
            except Exception as e_db:
                conn.rollback()
                raise RuntimeError(f"数据库批量写入时发生错误: {e_db}")

        scan_complete_message = f"扫描完成！共发现 {total} 部剧集，新增 {added_count} 部。"
        logger.info(scan_complete_message)
        
        if added_count > 0:
            logger.info("--- 任务链：即将自动触发【检查所有在追剧集】任务 ---")
            task_manager.update_status_from_thread(99, "扫描完成，正在启动追剧检查...")
            time.sleep(2)

            try:
                watchlist_proc = extensions.watchlist_processor_instance
                if watchlist_proc:
                    watchlist_proc.run_regular_processing_task(
                        progress_callback=task_manager.update_status_from_thread,
                        item_id=None
                    )
                    final_message = "自动化流程完成：扫描与追剧检查均已结束。"
                    task_manager.update_status_from_thread(100, final_message)
                else:
                    raise RuntimeError("WatchlistProcessor 未初始化，无法执行链式任务。")

            except Exception as e_chain:
                 logger.error(f"执行链式任务【检查所有在追剧集】时失败: {e_chain}", exc_info=True)
                 task_manager.update_status_from_thread(-1, f"链式任务失败: {e_chain}")

        else:
            final_message = f"任务完成！共扫描到 {total} 部剧集，没有发现可新增的剧集。"
            logger.info(final_message)
            task_manager.update_status_from_thread(100, final_message)

    except Exception as e:
        logger.error(f"执行 '{task_name}' 任务时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"任务失败: {e}")
# --- 任务链 ---
def task_run_chain(processor: MediaProcessor, task_sequence: list):
    """
    【V2 - 核心修复版】自动化任务链。
    按顺序执行指定的一系列任务，并为每个任务智能选择正确的处理器。
    """
    task_name = "自动化任务链"
    total_tasks = len(task_sequence)
    logger.info(f"--- '{task_name}' 已启动，共包含 {total_tasks} 个子任务 ---")
    task_manager.update_status_from_thread(0, f"任务链启动，共 {total_tasks} 个任务。")

    # 获取所有可用任务的定义
    registry = get_task_registry()
    
    # 遍历用户定义的任务序列
    for i, task_key in enumerate(task_sequence):
        # 注意：这里的 processor.is_stop_requested() 依赖于 task_manager 传递进来的默认处理器
        # 这是一个可以接受的设计，因为停止信号是全局的。
        if processor.is_stop_requested():
            logger.warning(f"'{task_name}' 被用户中止。")
            break

        task_info = registry.get(task_key)
        if not task_info:
            logger.error(f"任务链警告：在注册表中未找到任务 '{task_key}'，已跳过。")
            continue

        task_function, task_description = task_info
        
        progress = int((i / total_tasks) * 100)
        status_message = f"({i+1}/{total_tasks}) 正在执行: {task_description}"
        logger.info(f"--- {status_message} ---")
        task_manager.update_status_from_thread(progress, status_message)

        try:
            # ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
            # --- 【【【 这 是 核 心 修 改 点 2/2：智能选择处理器】】】 ---
            processor_to_use = None
            # 根据任务的唯一标识符 (key) 来判断使用哪个处理器
            if task_key in ['process-watchlist', 'refresh-single-watchlist-item']:
                processor_to_use = extensions.watchlist_processor_instance
                logger.trace(f"任务 '{task_description}' 将使用 WatchlistProcessor。")
            elif task_key in ['actor-tracking', 'scan-actor-media']:
                processor_to_use = extensions.actor_subscription_processor_instance
                logger.debug(f"任务 '{task_description}' 将使用 ActorSubscriptionProcessor。")
            else:
                # 默认情况下，使用通用的 MediaProcessor
                processor_to_use = extensions.media_processor_instance
                logger.debug(f"任务 '{task_description}' 将使用默认的 MediaProcessor。")

            if not processor_to_use:
                logger.error(f"任务链中的子任务 '{task_description}' 无法执行：对应的处理器未初始化，已跳过。")
                continue

            # ★★★ 使用我们刚刚智能选择的 `processor_to_use` 来执行任务 ★★★
            task_function(processor_to_use)
            # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
            
            # 子任务成功执行后，短暂等待，让状态更新能被前端捕获
            time.sleep(1) 

        except Exception as e:
            error_message = f"任务链中的子任务 '{task_description}' 执行失败: {e}"
            logger.error(error_message, exc_info=True)
            # 更新UI状态以反映错误，但任务链会继续
            task_manager.update_status_from_thread(progress, f"子任务'{task_description}'失败，继续...")
            time.sleep(3) # 让用户能看到错误信息
            continue # 继续下一个任务

    final_message = f"'{task_name}' 执行完毕。"
    if processor.is_stop_requested():
        final_message = f"'{task_name}' 已中止。"
    
    logger.info(f"--- {final_message} ---")
    task_manager.update_status_from_thread(100, "任务链已全部执行完毕。")
# --- 任务注册表 ---
def get_task_registry(context: str = 'all'):
    """
    【V4 - 最终完整版】
    返回一个包含所有可执行任务的字典。
    每个任务的定义现在是一个四元组：(函数, 描述, 处理器类型, 是否适合任务链)。
    """
    # 完整的任务注册表
    # 格式: 任务Key: (任务函数, 任务描述, 处理器类型, 是否适合在任务链中运行)
    full_registry = {
        'task-chain': (task_run_chain, "自动化任务链", 'media', False), # 任务链本身不能嵌套

        # --- 适合任务链的常规任务 ---
        'full-scan': (task_run_full_scan, "全量处理媒体", 'media', True),
        'sync-person-map': (task_sync_person_map, "同步演员映射", 'media', True),
        'enrich-aliases': (task_enrich_aliases, "演员数据补充", 'media', True),
        'populate-metadata': (task_populate_metadata_cache, "同步媒体数据", 'media', True),
        'process-watchlist': (task_process_watchlist, "智能追剧更新", 'watchlist', True),
        'actor-cleanup': (task_actor_translation_cleanup, "演员姓名翻译", 'media', True),
        'refresh-collections': (task_refresh_collections, "原生合集刷新", 'media', True),
        'custom-collections': (task_process_all_custom_collections, "自建合集刷新", 'media', True),
        'actor-tracking': (task_process_actor_subscriptions, "演员订阅扫描", 'actor', True),
        'generate-all-covers': (task_generate_all_covers, "生成所有封面", 'media', True),
        'auto-subscribe': (task_auto_subscribe, "智能订阅缺失", 'media', True),
        'sync-images-map': (task_full_image_sync, "覆盖缓存备份", 'media', True),

        # --- 不适合任务链的、需要特定参数的任务 ---
        'process_all_custom_collections': (task_process_all_custom_collections, "生成所有自建合集", 'media', False),
        'process-single-custom-collection': (task_process_custom_collection, "生成单个自建合集", 'media', False),
    }

    if context == 'chain':
        # ★★★ 核心修复 1/2：使用第四个元素 (布尔值) 来进行过滤 ★★★
        # 这将完美恢复您原来的功能
        return {
            key: (info[0], info[1]) 
            for key, info in full_registry.items() 
            if info[3]  # info[3] 就是那个 True/False 标志
        }
    
    # ★★★ 核心修复 2/2：默认情况下，返回前三个元素 ★★★
    # 这确保了“万用插座”API (/api/tasks/run) 能够正确解包，无需修改
    return {
        key: (info[0], info[1], info[2]) 
        for key, info in full_registry.items()
    }

# ★★★ 一键生成所有合集的后台任务，核心优化在于只获取一次Emby媒体库 ★★★
def task_process_all_custom_collections(processor: MediaProcessor):
    """
    【V3.1 - PG JSON 兼容版】
    - 修复了因 psycopg2 自动解析 JSON 字段而导致的 TypeError。
    """
    task_name = "生成所有自建合集"
    logger.trace(f"--- 开始执行 '{task_name}' 任务 ---")

    try:
        task_manager.update_status_from_thread(0, "正在获取所有启用的合集定义...")
        active_collections = db_handler.get_all_active_custom_collections()
        if not active_collections:
            logger.info("  -> 没有找到任何已启用的自定义合集，任务结束。")
            task_manager.update_status_from_thread(100, "没有已启用的合集。")
            return
        
        total = len(active_collections)
        logger.info(f"  -> 共找到 {total} 个已启用的自定义合集需要处理。")

        task_manager.update_status_from_thread(2, "正在从Emby获取全库媒体数据...")
        libs_to_process_ids = processor.config.get("libraries_to_process", [])
        if not libs_to_process_ids: raise ValueError("未在配置中指定要处理的媒体库。")
        
        movies = emby_handler.get_emby_library_items(base_url=processor.emby_url, api_key=processor.emby_api_key, user_id=processor.emby_user_id, media_type_filter="Movie", library_ids=libs_to_process_ids) or []
        series = emby_handler.get_emby_library_items(base_url=processor.emby_url, api_key=processor.emby_api_key, user_id=processor.emby_user_id, media_type_filter="Series", library_ids=libs_to_process_ids) or []
        all_emby_items = movies + series
        logger.info(f"  -> 已从Emby获取 {len(all_emby_items)} 个媒体项目。")

        task_manager.update_status_from_thread(5, "正在从Emby获取现有合集列表...")
        all_emby_collections = emby_handler.get_all_collections_from_emby_generic(
            base_url=processor.emby_url, api_key=processor.emby_api_key, user_id=processor.emby_user_id
        ) or []
        
        prefetched_collection_map = {coll.get('Name', '').lower(): coll for coll in all_emby_collections}
        logger.info(f"  -> 已预加载 {len(prefetched_collection_map)} 个现有合集的信息。")

        for i, collection in enumerate(active_collections):
            if processor.is_stop_requested():
                logger.warning("任务被用户中止。")
                break

            collection_id = collection['id']
            collection_name = collection['name']
            collection_type = collection['type']
            # ★★★ 核心修复：直接使用已经是字典的 definition_json 字段 ★★★
            definition = collection['definition_json']
            
            progress = 10 + int((i / total) * 90)
            task_manager.update_status_from_thread(progress, f"({i+1}/{total}) 正在处理: {collection_name}")

            try:
                item_types_for_collection = definition.get('item_type', ['Movie'])
                tmdb_items = []
                if collection_type == 'list' and definition.get('url', '').startswith('maoyan://'):
                    importer = ListImporter(processor.tmdb_api_key)
                    greenlet = gevent.spawn(importer._execute_maoyan_fetch, definition)
                    tmdb_items = greenlet.get()
                else:
                    if collection_type == 'list':
                        importer = ListImporter(processor.tmdb_api_key)
                        tmdb_items = importer.process(definition)
                    elif collection_type == 'filter':
                        engine = FilterEngine()
                        tmdb_items = engine.execute_filter(definition)
                
                tmdb_ids = [item['id'] for item in tmdb_items]

                if not tmdb_ids:
                    logger.warning(f"合集 '{collection_name}' 未能生成任何媒体ID，跳过。")
                    db_handler.update_custom_collection_after_sync(collection_id, {"emby_collection_id": None})
                    continue

                result_tuple = emby_handler.create_or_update_collection_with_tmdb_ids(
                    collection_name=collection_name, 
                    tmdb_ids=tmdb_ids, 
                    base_url=processor.emby_url,
                    api_key=processor.emby_api_key, 
                    user_id=processor.emby_user_id,
                    prefetched_emby_items=all_emby_items, 
                    prefetched_collection_map=prefetched_collection_map,
                    item_types=item_types_for_collection
                )
                
                if not result_tuple:
                    raise RuntimeError("在Emby中创建或更新合集失败。")
                
                emby_collection_id, tmdb_ids_in_library = result_tuple

                update_data = {
                    "emby_collection_id": emby_collection_id,
                    "item_type": json.dumps(definition.get('item_type', ['Movie'])),
                    "last_synced_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

                if collection_type == 'list':
                    previous_media_map = {}
                    try:
                        # ★★★ 核心修复：直接使用已经是列表的 generated_media_info_json 字段 ★★★
                        previous_media_list = collection.get('generated_media_info_json') or []
                        previous_media_map = {str(m.get('tmdb_id')): m for m in previous_media_list}
                    except TypeError:
                        logger.warning(f"解析合集 {collection_name} 的旧媒体JSON失败...")

                    existing_tmdb_ids = set(map(str, tmdb_ids_in_library))
                    image_tag = None
                    if emby_collection_id:
                        emby_collection_details = emby_handler.get_emby_item_details(emby_collection_id, processor.emby_url, processor.emby_api_key, processor.emby_user_id)
                        image_tag = emby_collection_details.get("ImageTags", {}).get("Primary")
                    
                    all_media_details = []
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        future_to_item = {executor.submit(tmdb_handler.get_movie_details if item['type'] != 'Series' else tmdb_handler.get_tv_details_tmdb, item['id'], processor.tmdb_api_key): item for item in tmdb_items}
                        for future in as_completed(future_to_item):
                            try:
                                detail = future.result()
                                if detail: all_media_details.append(detail)
                            except Exception as exc:
                                logger.error(f"获取TMDb详情时线程内出错: {exc}")
                    
                    all_media_with_status, has_missing, missing_count = [], False, 0
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    for media in all_media_details:
                        if not media: continue
                        media_tmdb_id = str(media.get("id"))
                        release_date = media.get("release_date") or media.get("first_air_date", '')
                        
                        if media_tmdb_id in existing_tmdb_ids: status = "in_library"
                        elif previous_media_map.get(media_tmdb_id, {}).get('status') == 'subscribed': status = "subscribed"
                        elif release_date and release_date > today_str: status = "unreleased"
                        else: status, has_missing, missing_count = "missing", True, missing_count + 1
                        
                        all_media_with_status.append({
                            "tmdb_id": media_tmdb_id, "title": media.get("title") or media.get("name"),
                            "release_date": release_date, "poster_path": media.get("poster_path"), "status": status
                        })

                    update_data.update({
                        "health_status": "has_missing" if has_missing else "ok",
                        "in_library_count": len(existing_tmdb_ids), "missing_count": missing_count,
                        "generated_media_info_json": json.dumps(all_media_with_status, ensure_ascii=False),
                        "poster_path": f"/Items/{emby_collection_id}/Images/Primary%stag={image_tag}" if image_tag and emby_collection_id else None
                    })
                else: 
                    update_data.update({
                        "health_status": "ok", "in_library_count": len(tmdb_ids_in_library),
                        "missing_count": 0, "generated_media_info_json": '[]', "poster_path": None
                    })
                
                db_handler.update_custom_collection_after_sync(collection_id, update_data)
                logger.info(f"  -> ✅ 合集 '{collection_name}' 处理完成，并已更新数据库状态。")

            except Exception as e_coll:
                logger.error(f"处理合集 '{collection_name}' (ID: {collection_id}) 时发生错误: {e_coll}", exc_info=True)
                continue

        try:
            cover_config_path = os.path.join(config_manager.PERSISTENT_DATA_PATH, "cover_generator.json")
            cover_config = {}
            if os.path.exists(cover_config_path):
                with open(cover_config_path, 'r', encoding='utf-8') as f:
                    cover_config = json.load(f)

            if cover_config.get("enabled"):
                logger.info("  -> 检测到封面生成器已启用，将为所有已处理的合集生成封面...")
                task_manager.update_status_from_thread(95, "合集同步完成，开始生成封面...")
                
                cover_service = CoverGeneratorService(config=cover_config)
                updated_collections = db_handler.get_all_active_custom_collections()

                for collection in updated_collections:
                    collection_name = collection.get('name')
                    emby_collection_id = collection.get('emby_collection_id')
                    
                    if emby_collection_id:
                        logger.info(f"  -> 正在为合集 '{collection_name}' 生成封面")
                        server_id = 'main_emby' 
                        
                        library_info = emby_handler.get_emby_item_details(
                            emby_collection_id, 
                            processor.emby_url, 
                            processor.emby_api_key, 
                            processor.emby_user_id
                        )
                        
                        if library_info:
                            item_count_to_pass = collection.get('in_library_count', 0)
                            if collection.get('type') == 'list':
                                item_count_to_pass = '榜单'
                            
                            cover_service.generate_for_library(
                                emby_server_id=server_id,
                                library=library_info,
                                item_count=item_count_to_pass
                            )
                        else:
                            logger.warning(f"无法获取 Emby 合集 {emby_collection_id} 的详情，跳过封面生成。")
                    else:
                        logger.debug(f"合集 '{collection_name}' 没有关联的 Emby ID，跳过封面生成。")

        except Exception as e:
            logger.error(f"在任务末尾执行批量封面生成时失败: {e}", exc_info=True)
        
        final_message = "所有启用的自定义合集均已处理完毕！"
        if processor.is_stop_requested(): final_message = "任务已中止。"
        
        task_manager.update_status_from_thread(100, final_message)
        logger.trace(f"--- '{task_name}' 任务成功完成 ---")

    except Exception as e:
        logger.error(f"执行 '{task_name}' 任务时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"任务失败: {e}")

# --- 处理单个自定义合集的核心任务 ---
def task_process_custom_collection(processor: MediaProcessor, custom_collection_id: int):
    """
    【V8.1 - PG JSON 兼容版】
    - 修复了因 psycopg2 自动解析 JSON 字段而导致的 TypeError。
    - 不再对从数据库中获取的 _json 字段执行 json.loads()。
    """
    task_name = f"处理自定义合集 (ID: {custom_collection_id})"
    logger.trace(f"--- 开始执行 '{task_name}' 任务 ---")
    
    try:
        task_manager.update_status_from_thread(0, "正在读取合集定义...")
        collection = db_handler.get_custom_collection_by_id(custom_collection_id)
        if not collection: raise ValueError(f"未找到ID为 {custom_collection_id} 的自定义合集。")
        
        collection_name = collection['name']
        collection_type = collection['type']
        # ★★★ 核心修复：直接使用已经是字典的 definition_json 字段 ★★★
        definition = collection['definition_json']
        
        item_types_for_collection = definition.get('item_type', ['Movie'])
        
        tmdb_items = []
        if collection_type == 'list' and definition.get('url', '').startswith('maoyan://'):
            logger.info(f"检测到猫眼榜单 '{collection_name}'，将启动异步后台任务...")
            task_manager.update_status_from_thread(10, f"正在后台获取猫眼榜单: {collection_name}...")
            importer = ListImporter(processor.tmdb_api_key)
            greenlet = gevent.spawn(importer._execute_maoyan_fetch, definition)
            tmdb_items = greenlet.get()
        else:
            if collection_type == 'list':
                importer = ListImporter(processor.tmdb_api_key)
                tmdb_items = importer.process(definition)
            elif collection_type == 'filter':
                engine = FilterEngine()
                tmdb_items = engine.execute_filter(definition)
        
        tmdb_ids = [item['id'] for item in tmdb_items]
        
        if not tmdb_ids:
            logger.warning(f"合集 '{collection_name}' 未能生成任何媒体ID，任务结束。")
            return

        task_manager.update_status_from_thread(70, f"已生成 {len(tmdb_items)} 个ID，正在Emby中创建/更新合集...")
        libs_to_process_ids = processor.config.get("libraries_to_process", [])

        result_tuple = emby_handler.create_or_update_collection_with_tmdb_ids(
            collection_name=collection_name, 
            tmdb_ids=tmdb_ids, 
            base_url=processor.emby_url,
            api_key=processor.emby_api_key, 
            user_id=processor.emby_user_id,
            library_ids=libs_to_process_ids, 
            item_types=item_types_for_collection
        )

        if not result_tuple:
            raise RuntimeError("在Emby中创建或更新合集失败。")
        
        emby_collection_id, tmdb_ids_in_library = result_tuple

        update_data = {
            "emby_collection_id": emby_collection_id,
            "item_type": json.dumps(definition.get('item_type', ['Movie'])), # 写入时需要转为字符串
            "last_synced_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        if collection_type == 'list':
            task_manager.update_status_from_thread(90, "榜单合集已同步，正在并行获取详情...")
            
            previous_media_map = {}
            try:
                # ★★★ 核心修复：直接使用已经是列表的 generated_media_info_json 字段 ★★★
                previous_media_list = collection.get('generated_media_info_json') or []
                previous_media_map = {str(m.get('tmdb_id')): m for m in previous_media_list}
            except TypeError:
                logger.warning(f"解析合集 {collection_name} 的旧媒体JSON失败...")

            existing_tmdb_ids = set(map(str, tmdb_ids_in_library))
            
            image_tag = None
            if emby_collection_id:
                emby_collection_details = emby_handler.get_emby_item_details(emby_collection_id, processor.emby_url, processor.emby_api_key, processor.emby_user_id)
                image_tag = emby_collection_details.get("ImageTags", {}).get("Primary")
            
            all_media_details = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_item = {executor.submit(tmdb_handler.get_movie_details if item['type'] != 'Series' else tmdb_handler.get_tv_details_tmdb, item['id'], processor.tmdb_api_key): item for item in tmdb_items}
                for future in as_completed(future_to_item):
                    try:
                        detail = future.result()
                        if detail: all_media_details.append(detail)
                    except Exception as exc:
                        logger.error(f"获取TMDb详情时线程内出错: {exc}")
            
            all_media_with_status, has_missing, missing_count = [], False, 0
            today_str = datetime.now().strftime('%Y-%m-%d')
            for media in all_media_details:
                if not media: continue
                media_tmdb_id = str(media.get("id"))
                release_date = media.get("release_date") or media.get("first_air_date", '')
            
                if media_tmdb_id in existing_tmdb_ids: media_status = "in_library"
                elif previous_media_map.get(media_tmdb_id, {}).get('status') == 'subscribed': media_status = "subscribed"
                elif release_date and release_date > today_str: media_status = "unreleased"
                else: media_status, has_missing, missing_count = "missing", True, missing_count + 1
                
                all_media_with_status.append({
                    "tmdb_id": media_tmdb_id, "title": media.get("title") or media.get("name"),
                    "release_date": release_date, "poster_path": media.get("poster_path"), "status": media_status
                })

            update_data.update({
                "health_status": "has_missing" if has_missing else "ok",
                "in_library_count": len(existing_tmdb_ids), "missing_count": missing_count,
                "generated_media_info_json": json.dumps(all_media_with_status, ensure_ascii=False),
                "poster_path": f"/Items/{emby_collection_id}/Images/Primary?tag={image_tag}" if image_tag and emby_collection_id else None
            })
            logger.info(f"  -> 已为RSS合集 '{collection_name}' 分析健康状态。")
        else: 
            task_manager.update_status_from_thread(95, "筛选合集已生成，跳过缺失分析。")
            update_data.update({
                "health_status": "ok", "in_library_count": len(tmdb_ids_in_library),
                "missing_count": 0, "generated_media_info_json": '[]', "poster_path": None
            })

        db_handler.update_custom_collection_after_sync(custom_collection_id, update_data)
        logger.info(f"  -> 已更新自定义合集 '{collection_name}' (ID: {custom_collection_id}) 的同步状态和健康信息。")

        try:
            cover_config_path = os.path.join(config_manager.PERSISTENT_DATA_PATH, "cover_generator.json")
            cover_config = {}
            if os.path.exists(cover_config_path):
                with open(cover_config_path, 'r', encoding='utf-8') as f:
                    cover_config = json.load(f)

            if cover_config.get("enabled"):
                logger.info(f"  -> 检测到封面生成器已启用，将为合集 '{collection_name}' 生成封面...")
                cover_service = CoverGeneratorService(config=cover_config)
                if emby_collection_id:
                    server_id = 'main_emby' 
                    library_info = emby_handler.get_emby_item_details(
                        emby_collection_id, 
                        processor.emby_url, 
                        processor.emby_api_key, 
                        processor.emby_user_id
                    )
                    if library_info:
                        in_library_count = update_data.get('in_library_count', 0)
                        item_count_to_pass = in_library_count
                        if collection_type == 'list':
                            item_count_to_pass = '榜单'
                        cover_service.generate_for_library(
                            emby_server_id=server_id,
                            library=library_info,
                            item_count=item_count_to_pass
                        )
                    else:
                        logger.warning(f"无法获取 Emby 合集 {emby_collection_id} 的详情，跳过封面生成。")
        except Exception as e:
            logger.error(f"为合集 '{collection_name}' 生成封面时发生错误: {e}", exc_info=True)

        task_manager.update_status_from_thread(100, "自定义合集同步并分析完成！")

    except Exception as e:
        logger.error(f"执行 '{task_name}' 任务时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"任务失败: {e}")
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★★★ 新增：轻量级的元数据缓存填充任务 ★★★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
def task_populate_metadata_cache(processor: 'MediaProcessor', batch_size: int = 50, force_full_update: bool = False):
    """
    【V3.3 - 最终修复版】
    - 彻底修复了快速同步模式下的时间戳比较逻辑。
    - 之前的版本错误地尝试对 psycopg2 返回的 datetime 对象再次进行解析。
    - 此版本直接使用 psycopg2 返回的 datetime 对象进行比较，完全解决了差异计算失效的问题。
    """
    task_name = "同步媒体数据"
    sync_mode = "深度同步" if force_full_update else "快速同步"
    logger.info(f"--- 模式: {sync_mode} (分批大小: {batch_size}) ---")
    
    try:
        # ======================================================================
        # 步骤 1: 计算差异 (根据模式选择不同逻辑)
        # ======================================================================
        task_manager.update_status_from_thread(0, f"阶段1/2: 计算媒体库差异 ({sync_mode})...")
        
        libs_to_process_ids = processor.config.get("libraries_to_process", [])
        if not libs_to_process_ids:
            raise ValueError("未在配置中指定要处理的媒体库。")

        emby_items_index = emby_handler.get_emby_library_items(
            base_url=processor.emby_url, api_key=processor.emby_api_key, user_id=processor.emby_user_id,
            media_type_filter="Movie,Series", library_ids=libs_to_process_ids,
            fields="ProviderIds,Type,DateCreated,Name,ProductionYear,OriginalTitle,PremiereDate,CommunityRating,Genres,Studios,ProductionLocations,People,Tags,DateModified"
        ) or []
        
        emby_items_map = {
            item.get("ProviderIds", {}).get("Tmdb"): item 
            for item in emby_items_index if item.get("ProviderIds", {}).get("Tmdb")
        }
        emby_tmdb_ids = set(emby_items_map.keys())
        logger.info(f"  -> 从 Emby 获取到 {len(emby_tmdb_ids)} 个有效的媒体项。")

        db_sync_info = {}
        with db_handler.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tmdb_id, last_synced_at FROM media_metadata")
            for row in cursor.fetchall():
                db_sync_info[row["tmdb_id"]] = row["last_synced_at"] # <-- 这里存入的是 datetime 对象
        db_tmdb_ids = set(db_sync_info.keys())
        logger.info(f"  -> 从本地数据库 media_metadata 表中获取到 {len(db_tmdb_ids)} 个媒体项。")

        items_to_add_tmdb_ids = emby_tmdb_ids - db_tmdb_ids
        items_to_delete_tmdb_ids = db_tmdb_ids - emby_tmdb_ids
        common_ids = emby_tmdb_ids.intersection(db_tmdb_ids)
        
        if force_full_update:
            logger.info("  -> 深度同步模式：所有已存在项目都将被更新。")
            items_to_update_tmdb_ids = common_ids
        else:
            logger.info("  -> 快速同步模式：仅更新时间戳已变化的媒体。")
            items_to_update_tmdb_ids = set()
            for tmdb_id in common_ids:
                emby_item = emby_items_map.get(tmdb_id)
                # 为了清晰，重命名变量
                last_synced_dt_from_db = db_sync_info.get(tmdb_id)
                emby_modified_str = emby_item.get("DateModified")

                if not emby_modified_str or not last_synced_dt_from_db:
                    items_to_update_tmdb_ids.add(tmdb_id)
                    continue
                
                try:
                    emby_modified_str_fixed = re.sub(r'\.(\d{6})\d*Z$', r'.\1Z', emby_modified_str)
                    emby_modified_dt = datetime.fromisoformat(emby_modified_str_fixed.replace('Z', '+00:00'))
                    
                    # ★★★ 最终修复：直接使用从数据库获取的 datetime 对象，不再调用 fromisoformat ★★★
                    last_synced_dt = last_synced_dt_from_db

                    if emby_modified_dt > last_synced_dt:
                        items_to_update_tmdb_ids.add(tmdb_id)
                except (ValueError, TypeError) as e:
                    logger.warning(f"解析时间戳时遇到问题 (TMDb ID: {tmdb_id}), 将默认更新此项目。错误: {e}")
                    items_to_update_tmdb_ids.add(tmdb_id)

        logger.info(f"  -> 计算差异完成：新增 {len(items_to_add_tmdb_ids)} 项, 更新 {len(items_to_update_tmdb_ids)} 项, 删除 {len(items_to_delete_tmdb_ids)} 项。")

        if items_to_delete_tmdb_ids:
            logger.info(f"  -> 正在从数据库中删除 {len(items_to_delete_tmdb_ids)} 个已不存在的媒体项...")
            with db_handler.get_db_connection() as conn:
                cursor = conn.cursor()
                ids_to_delete_list = list(items_to_delete_tmdb_ids)
                for i in range(0, len(ids_to_delete_list), 500):
                    batch_ids = ids_to_delete_list[i:i+500]
                    sql = "DELETE FROM media_metadata WHERE tmdb_id = ANY(%s)"
                    cursor.execute(sql, (batch_ids,))
                conn.commit()
            logger.info("  -> 冗余数据清理完成。")

        ids_to_process = items_to_add_tmdb_ids.union(items_to_update_tmdb_ids)
        items_to_process = [emby_items_map[tmdb_id] for tmdb_id in ids_to_process]
        
        total_to_process = len(items_to_process)
        if total_to_process == 0:
            task_manager.update_status_from_thread(100, "数据库已是最新，无需同步。")
            return

        logger.info(f"  -> 总共需要处理 {total_to_process} 项，将分 { (total_to_process + batch_size - 1) // batch_size } 个批次。")

        # ======================================================================
        # 步骤 2: 分批循环处理需要新增/更新的媒体项
        # ======================================================================
        
        processed_count = 0
        for i in range(0, total_to_process, batch_size):
            if processor.is_stop_requested():
                logger.info("任务在批次处理前被中止。")
                break

            batch_items = items_to_process[i:i + batch_size]
            batch_number = (i // batch_size) + 1
            total_batches = (total_to_process + batch_size - 1) // batch_size
            
            logger.info(f"--- 开始处理批次 {batch_number}/{total_batches} (包含 {len(batch_items)} 个项目) ---")
            task_manager.update_status_from_thread(
                10 + int((processed_count / total_to_process) * 90), 
                f"处理批次 {batch_number}/{total_batches}..."
            )

            batch_people_to_enrich = [p for item in batch_items for p in item.get("People", [])]
            enriched_people_list = processor._enrich_cast_from_db_and_api(batch_people_to_enrich)
            enriched_people_map = {str(p.get("Id")): p for p in enriched_people_list}

            logger.info(f"  -> 开始从Tmdb补充导演/国家数据...")
            tmdb_details_map = {}
            def fetch_tmdb_details(item):
                tmdb_id = item.get("ProviderIds", {}).get("Tmdb")
                item_type = item.get("Type")
                if not tmdb_id: return None, None
                details = None
                if item_type == 'Movie':
                    details = tmdb_handler.get_movie_details(tmdb_id, processor.tmdb_api_key)
                elif item_type == 'Series':
                    details = tmdb_handler.get_tv_details_tmdb(tmdb_id, processor.tmdb_api_key)
                return tmdb_id, details

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_tmdb_id = {executor.submit(fetch_tmdb_details, item): item.get("ProviderIds", {}).get("Tmdb") for item in batch_items}
                for future in concurrent.futures.as_completed(future_to_tmdb_id):
                    tmdb_id, details = future.result()
                    if tmdb_id and details:
                        tmdb_details_map[tmdb_id] = details
            
            metadata_batch = []
            for item in batch_items:
                tmdb_id = item.get("ProviderIds", {}).get("Tmdb")
                if not tmdb_id: continue

                full_details_emby = item
                tmdb_details = tmdb_details_map.get(tmdb_id)

                actors = []
                for person in full_details_emby.get("People", []):
                    person_id = str(person.get("Id"))
                    enriched_person = enriched_people_map.get(person_id)
                    if enriched_person and enriched_person.get("ProviderIds", {}).get("Tmdb"):
                        actors.append({'id': enriched_person["ProviderIds"]["Tmdb"], 'name': enriched_person.get('Name')})
                
                directors, countries = [], []
                if tmdb_details:
                    item_type = full_details_emby.get("Type")
                    if item_type == 'Movie':
                        credits_data = tmdb_details.get("credits", {}) or tmdb_details.get("casts", {})
                        if credits_data:
                            directors = [{'id': p.get('id'), 'name': p.get('name')} for p in credits_data.get('crew', []) if p.get('job') == 'Director']
                        countries = translate_country_list([c['name'] for c in tmdb_details.get('production_countries', [])])
                    elif item_type == 'Series':
                        credits_data = tmdb_details.get("credits", {})
                        if credits_data:
                            directors = [{'id': p.get('id'), 'name': p.get('name')} for p in credits_data.get('crew', []) if p.get('job') == 'Director']
                        if not directors: directors = [{'id': c.get('id'), 'name': c.get('name')} for c in tmdb_details.get('created_by', [])]
                        countries = translate_country_list(tmdb_details.get('origin_country', []))

                studios = [s['Name'] for s in full_details_emby.get('Studios', []) if s.get('Name')]
                release_date_str = (full_details_emby.get('PremiereDate') or '0000-01-01T00:00:00.000Z').split('T')[0]
                tags = [tag['Name'] for tag in full_details_emby.get('TagItems', []) if tag.get('Name')]
                metadata_to_save = {
                    "tmdb_id": tmdb_id, "item_type": full_details_emby.get("Type"),
                    "title": full_details_emby.get('Name'), "original_title": full_details_emby.get('OriginalTitle'),
                    "release_year": full_details_emby.get('ProductionYear'), "rating": full_details_emby.get('CommunityRating'),
                    "release_date": release_date_str, "date_added": (full_details_emby.get("DateCreated") or '').split('T')[0] or None,
                    "genres_json": json.dumps(full_details_emby.get('Genres', []), ensure_ascii=False),
                    "actors_json": json.dumps(actors, ensure_ascii=False),
                    "directors_json": json.dumps(directors, ensure_ascii=False),
                    "studios_json": json.dumps(studios, ensure_ascii=False),
                    "countries_json": json.dumps(countries, ensure_ascii=False),
                    "tags_json": json.dumps(tags, ensure_ascii=False),
                }
                metadata_batch.append(metadata_to_save)

            if metadata_batch:
                with db_handler.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("BEGIN TRANSACTION;")
                    for metadata in metadata_batch:
                        try:
                            columns = list(metadata.keys())
                            columns_str = ', '.join(columns)
                            placeholders_str = ', '.join(['%s'] * len(columns))
                            
                            update_clauses = [f"{col} = EXCLUDED.{col}" for col in columns]
                            update_clauses.append("last_synced_at = EXCLUDED.last_synced_at")
                            update_str = ', '.join(update_clauses)

                            sql = f"""
                                INSERT INTO media_metadata ({columns_str}, last_synced_at)
                                VALUES ({placeholders_str}, %s)
                                ON CONFLICT (tmdb_id, item_type) DO UPDATE SET {update_str}
                            """
                            sync_time = datetime.now(timezone.utc).isoformat()
                            cursor.execute(sql, tuple(metadata.values()) + (sync_time,))
                        except psycopg2.Error as e:
                            logger.error(f"写入 TMDB ID {metadata.get('tmdb_id')} 的元数据时发生数据库错误: {e}")
                    conn.commit()
                logger.info(f"--- 批次 {batch_number}/{total_batches} 已成功写入数据库。---")
            
            processed_count += len(batch_items)

        final_message = f"同步完成！本次处理 {processed_count}/{total_to_process} 项, 删除 {len(items_to_delete_tmdb_ids)} 项。"
        task_manager.update_status_from_thread(100, final_message)
        logger.trace(f"--- '{task_name}' 任务成功完成 ---")

    except Exception as e:
        logger.error(f"执行 '{task_name}' 任务时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"任务失败: {e}")
        

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★★★ 新增：立即生成所有媒体库封面的后台任务 ★★★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
def task_generate_all_covers(processor: MediaProcessor):
    """
    后台任务：为所有（未被忽略的）媒体库生成封面。
    """
    task_name = "一键生成所有媒体库封面"
    logger.trace(f"--- 开始执行 '{task_name}' 任务 ---")
    
    try:
        # 1. 读取配置
        cover_config_path = os.path.join(config_manager.PERSISTENT_DATA_PATH, "cover_generator.json")
        if not os.path.exists(cover_config_path):
            task_manager.update_status_from_thread(-1, "错误：找不到封面生成器配置文件。")
            return

        with open(cover_config_path, 'r', encoding='utf-8') as f:
            cover_config = json.load(f)

        if not cover_config.get("enabled"):
            task_manager.update_status_from_thread(100, "任务跳过：封面生成器未启用。")
            return

        # 2. 获取媒体库列表
        task_manager.update_status_from_thread(5, "正在获取所有媒体库列表...")
        all_libraries = emby_handler.get_emby_libraries(
            emby_server_url=processor.emby_url,
            emby_api_key=processor.emby_api_key,
            user_id=processor.emby_user_id
        )
        if not all_libraries:
            task_manager.update_status_from_thread(-1, "错误：未能从Emby获取到任何媒体库。")
            return
        
        # 3. 筛选媒体库
        # ★★★ 核心修复：直接使用原始ID进行比较 ★★★
        exclude_ids = set(cover_config.get("exclude_libraries", []))
        # 允许处理的媒体库类型列表，增加了 'audiobooks'
        ALLOWED_COLLECTION_TYPES = ['movies', 'tvshows', 'boxsets', 'mixed', 'music', 'audiobooks']

        libraries_to_process = [
            lib for lib in all_libraries 
            if lib.get('Id') not in exclude_ids
            and (
                # 条件1：满足常规的 CollectionType
                lib.get('CollectionType') in ALLOWED_COLLECTION_TYPES
                # 条件2：或者，是“混合库测试”这种特殊的 CollectionFolder
                or lib.get('Type') == 'CollectionFolder' 
            )
        ]
        
        total = len(libraries_to_process)
        if total == 0:
            task_manager.update_status_from_thread(100, "任务完成：没有需要处理的媒体库。")
            return
            
        logger.info(f"  -> 将为 {total} 个媒体库生成封面: {[lib['Name'] for lib in libraries_to_process]}")
        
        # 4. 实例化服务并循环处理
        cover_service = CoverGeneratorService(config=cover_config)
        
        TYPE_MAP = {
            'movies': 'Movie', 
            'tvshows': 'Series', 
            'music': 'MusicAlbum',
            'boxsets': 'BoxSet', 
            'mixed': 'Movie,Series',
            'audiobooks': 'AudioBook'  # <-- 增加有声读物的映射
        }

        for i, library in enumerate(libraries_to_process):
            if processor.is_stop_requested(): break
            
            progress = 10 + int((i / total) * 90)
            task_manager.update_status_from_thread(progress, f"({i+1}/{total}) 正在处理: {library.get('Name')}")
            
            try:
                library_id = library.get('Id')
                collection_type = library.get('CollectionType')
                item_type_to_query = None # 先重置

                # --- ★★★ 核心修复 3：使用更精确的 if/elif 逻辑判断查询类型 ★★★ ---
                # 优先使用 CollectionType 进行判断，这是最准确的
                if collection_type:
                    item_type_to_query = TYPE_MAP.get(collection_type)
                
                # 如果 CollectionType 不存在，再使用 Type == 'CollectionFolder' 作为备用方案
                # 这专门用于处理像“混合库测试”那样的特殊库
                elif library.get('Type') == 'CollectionFolder':
                    logger.info(f"媒体库 '{library.get('Name')}' 是一个特殊的 CollectionFolder，将查询电影和剧集。")
                    item_type_to_query = 'Movie,Series'
                # --- 修复结束 ---

                item_count = 0
                if library_id and item_type_to_query:
                    item_count = emby_handler.get_item_count(
                        base_url=processor.emby_url,
                        api_key=processor.emby_api_key,
                        user_id=processor.emby_user_id,
                        parent_id=library_id,
                        item_type=item_type_to_query
                    ) or 0

                cover_service.generate_for_library(
                    emby_server_id='main_emby', # 这里的 server_id 只是一个占位符，不影响忽略逻辑
                    library=library,
                    item_count=item_count
                )
            except Exception as e_gen:
                logger.error(f"为媒体库 '{library.get('Name')}' 生成封面时发生错误: {e_gen}", exc_info=True)
                continue
        
        final_message = "所有媒体库封面已处理完毕！"
        if processor.is_stop_requested(): final_message = "任务已中止。"
        task_manager.update_status_from_thread(100, final_message)

    except Exception as e:
        logger.error(f"执行 '{task_name}' 任务时发生严重错误: {e}", exc_info=True)
        task_manager.update_status_from_thread(-1, f"任务失败: {e}")