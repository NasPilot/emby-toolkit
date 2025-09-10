# routes/resubscribe.py (多规则改造最终版)

from flask import Blueprint, request, jsonify
import logging
import db_handler
import tasks
import task_manager
import moviepilot_handler
import config_manager
import extensions
import emby_handler
from extensions import login_required, task_lock_required

resubscribe_bp = Blueprint('resubscribe', __name__, url_prefix='/api/resubscribe')
logger = logging.getLogger(__name__)

# ======================================================================
# ★★★ 规则管理 (Rules Management) - RESTful API ★★★
# ======================================================================

@resubscribe_bp.route('/rules', methods=['GET'])
@login_required
def get_rules():
    """获取所有洗版规则列表。"""
    try:
        rules = db_handler.get_all_resubscribe_rules()
        return jsonify(rules)
    except Exception as e:
        logger.error(f"API: 获取洗版规则列表失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500

@resubscribe_bp.route('/rules', methods=['POST'])
@login_required
def create_rule():
    """创建一条新的洗版规则。"""
    try:
        rule_data = request.json
        if not rule_data or not rule_data.get('name'):
            return jsonify({"error": "规则名称不能为空"}), 400
        
        new_id = db_handler.create_resubscribe_rule(rule_data)
        return jsonify({"message": "洗版规则已成功创建！", "id": new_id}), 201
    except Exception as e:
        # 捕获由 db_handler 抛出的唯一性冲突
        if "UNIQUE constraint failed" in str(e) or "violates unique constraint" in str(e):
             return jsonify({"error": f"创建失败：规则名称 '{rule_data.get('name')}' 已存在。"}), 409
        logger.error(f"API: 创建洗版规则失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500

@resubscribe_bp.route('/rules/<int:rule_id>', methods=['PUT'])
@login_required
def update_rule(rule_id):
    """更新指定ID的洗版规则。"""
    try:
        rule_data = request.json
        if not rule_data:
            return jsonify({"error": "请求体不能为空"}), 400
        
        success = db_handler.update_resubscribe_rule(rule_id, rule_data)
        if success:
            return jsonify({"message": "洗版规则已成功更新！"})
        else:
            return jsonify({"error": f"未找到ID为 {rule_id} 的规则"}), 404
    except Exception as e:
        logger.error(f"API: 更新洗版规则 {rule_id} 失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500

@resubscribe_bp.route('/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_rule(rule_id):
    """删除指定ID的洗版规则。"""
    try:
        logger.info(f"API: 准备删除规则 {rule_id}，将首先清理其关联的缓存...")
        db_handler.delete_resubscribe_cache_by_rule_id(rule_id)
        success = db_handler.delete_resubscribe_rule(rule_id)
        if success:
            return jsonify({"message": "洗版规则已成功删除！"})
        else:
            return jsonify({"error": f"未找到ID为 {rule_id} 的规则"}), 404
    except Exception as e:
        logger.error(f"API: 删除洗版规则 {rule_id} 失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500

@resubscribe_bp.route('/rules/order', methods=['POST'])
@login_required
def update_rules_order():
    """更新所有规则的排序。"""
    try:
        ordered_ids = request.json
        if not isinstance(ordered_ids, list):
            return jsonify({"error": "请求体必须是一个ID数组"}), 400
        
        db_handler.update_resubscribe_rules_order(ordered_ids)
        return jsonify({"message": "规则顺序已更新！"})
    except Exception as e:
        logger.error(f"API: 更新规则顺序失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500

# ======================================================================
# ★★★ 海报墙与任务触发 (Library & Tasks) - 保持不变 ★★★
# ======================================================================

@resubscribe_bp.route('/library_status', methods=['GET'])
@login_required
def get_library_status():
    """获取海报墙数据。"""
    try:
        items = db_handler.get_all_resubscribe_cache()
        return jsonify(items)
    except Exception as e:
        logger.error(f"API: 获取洗版状态缓存失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500

@resubscribe_bp.route('/refresh_status', methods=['POST'])
@login_required
@task_lock_required
def trigger_refresh_status():
    """触发缓存刷新任务。"""
    try:
        task_manager.submit_task(
            tasks.task_update_resubscribe_cache,
            task_name="刷新媒体洗版状态",
            processor_type='media'
        )
        return jsonify({"message": "刷新媒体洗版状态任务已提交！"}), 202
    except Exception as e:
        return jsonify({"error": f"提交任务失败: {e}"}), 500

@resubscribe_bp.route('/resubscribe_all', methods=['POST'])
@login_required
@task_lock_required
def trigger_resubscribe_all():
    """触发一键洗版全部的任务。"""
    try:
        task_manager.submit_task(
            tasks.task_resubscribe_library,
            task_name="全库媒体洗版",
            processor_type='media'
        )
        return jsonify({"message": "一键洗版任务已提交！"}), 202
    except Exception as e:
        return jsonify({"error": f"提交任务失败: {e}"}), 500

@resubscribe_bp.route('/resubscribe_item', methods=['POST'])
@login_required
def resubscribe_single_item():
    """
    【V3 - 标准化配置源】API端点：为单个媒体项提交洗版订阅。
    """
    data = request.json
    item_id = data.get('item_id')
    item_name = data.get('item_name')
    tmdb_id = data.get('tmdb_id')
    item_type = data.get('item_type')

    if not all([item_id, item_name, tmdb_id, item_type]):
        return jsonify({"error": "请求中缺少必要的媒体项参数"}), 400

    try:
        current_quota = db_handler.get_subscription_quota()
        if current_quota <= 0:
            return jsonify({"error": "今日订阅配额已用尽，请明天再试。"}), 429

        # --- ★★★ 核心修复 1/2: 从核心处理器获取配置，而不是全局字典 ★★★
        processor = extensions.media_processor_instance
        if not processor:
            return jsonify({"error": "核心处理器未初始化"}), 503
            
        payload = {
            "name": item_name,
            "tmdbid": int(tmdb_id),
            "type": "电影" if item_type == "Movie" else "电视剧",
            "best_version": 1
        }
        
        # 使用 processor.config 这个可靠的数据源
        success = moviepilot_handler.subscribe_with_custom_payload(payload, processor.config)
        
        if success:
            db_handler.decrement_subscription_quota()
            
            message = f"《{item_name}》的洗版请求已成功提交！"
            
            cache_item = db_handler.get_resubscribe_cache_item(item_id)
            rule_to_check = None
            if cache_item and cache_item.get('matched_rule_id'):
                rule_to_check = db_handler.get_resubscribe_rule_by_id(cache_item['matched_rule_id'])

            # --- ★★★ 核心逻辑改造：根据规则决定是“删除”还是“更新” ★★★ ---
            if rule_to_check and rule_to_check.get('delete_after_resubscribe'):
                logger.warning(f"规则 '{rule_to_check['name']}' 要求删除源文件，正在为项目 {item_name} 执行删除...")
                delete_success = emby_handler.delete_item(
                    item_id=item_id, emby_server_url=processor.emby_url,
                    emby_api_key=processor.emby_api_key, user_id=processor.emby_user_id
                )
                if delete_success:
                    db_handler.delete_resubscribe_cache_item(item_id)
                    message += " Emby中的源文件已根据规则删除，并已从洗版列表移除。"
                else:
                    db_handler.update_resubscribe_item_status(item_id, 'subscribed')
                    message += " 但根据规则删除Emby源文件时失败。"
            else:
                db_handler.update_resubscribe_item_status(item_id, 'subscribed')

            return jsonify({"message": message})
        else:
            return jsonify({"error": "提交洗版请求失败..."}), 500
            
    except Exception as e:
        logger.error(f"API: 处理单独洗版请求时发生未知错误: {e}", exc_info=True)
        return jsonify({"error": f"处理请求时发生服务器内部错误: {e}"}), 500
    
# ★★★ 新增：为洗版规则提供媒体库选项的 API ★★★
@resubscribe_bp.route('/libraries', methods=['GET'])
@login_required
def get_emby_libraries_for_rules():
    """
    获取所有 Emby 媒体库，并返回一个精简的列表 (label, value)，
    专门用于洗版规则设置页面的下拉选择框。
    """
    try:
        if not extensions.media_processor_instance or \
           not extensions.media_processor_instance.emby_url or \
           not extensions.media_processor_instance.emby_api_key:
            return jsonify({"error": "Emby配置不完整或服务未就绪"}), 503

        full_libraries_list = emby_handler.get_emby_libraries(
            extensions.media_processor_instance.emby_url,
            extensions.media_processor_instance.emby_api_key,
            extensions.media_processor_instance.emby_user_id
        )

        if full_libraries_list is None:
            return jsonify({"error": "无法获取Emby媒体库列表"}), 500
        
        simplified_libraries = [
            {'label': item.get('Name'), 'value': item.get('Id')}
            for item in full_libraries_list
            if item.get('Name') and item.get('Id') and item.get('CollectionType') in ['movies', 'tvshows', 'mixed']
        ]
        
        return jsonify(simplified_libraries)

    except Exception as e:
        logger.error(f"API: 获取洗版用媒体库列表时失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500