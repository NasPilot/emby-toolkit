# custom_collection_handler.py
import logging
import requests
import xml.etree.ElementTree as ET
import re
import os
import sys
from typing import List, Dict, Any, Optional, Tuple
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ★★★ 核心修正：再次回归 gevent.subprocess ★★★
from gevent import subprocess, Timeout

import tmdb_handler
import config_manager
import db_handler 
from tmdb_handler import search_media, get_tv_details_tmdb

logger = logging.getLogger(__name__)


class ListImporter:
    """
    (V9.1 - 最终异步版)
    使用 gevent.subprocess，并确保在独立的 greenlet 中运行，
    从而实现真正的非阻塞异步执行。
    """
    
    SEASON_PATTERN = re.compile(r'(.*?)\s*[（(]?\s*(第?[一二三四五六七八九十百]+)\s*季\s*[)）]?$')
    CHINESE_NUM_MAP = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        '第一': 1, '第二': 2, '第三': 3, '第四': 4, '第五': 5, '第六': 6, '第七': 7, '第八': 8, '第九': 9, '第十': 10,
        '第十一': 11, '十二': 12, '第十三': 13, '第十四': 14, '第十五': 15
    }
    VALID_MAOYAN_PLATFORMS = {'tencent', 'iqiyi', 'youku', 'mango'}

    def __init__(self, tmdb_api_key: str):
        self.tmdb_api_key = tmdb_api_key
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

    # ★★★ 核心修改：这个函数现在是纯粹的阻塞执行逻辑 ★★★
    def _execute_maoyan_fetch(self, definition: Dict) -> List[Dict[str, str]]:
        maoyan_url = definition.get('url', '')
        temp_output_file = os.path.join(config_manager.PERSISTENT_DATA_PATH, f"maoyan_temp_output_{hash(maoyan_url)}.json")
        
        content_key = maoyan_url.replace('maoyan://', '')
        parts = content_key.split('-')
        
        platform = 'all'
        if len(parts) > 1 and parts[-1] in self.VALID_MAOYAN_PLATFORMS:
            platform = parts[-1]
            type_part = '-'.join(parts[:-1])
        else:
            type_part = content_key

        types_to_fetch = [t.strip() for t in type_part.split(',') if t.strip()]
        
        if not types_to_fetch:
            logger.error(f"无法从猫眼URL '{maoyan_url}' 中解析出有效的类型。")
            return []
            
        limit = definition.get('limit')
        if not limit:
            limit = 50

        fetcher_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maoyan_fetcher.py')
        if not os.path.exists(fetcher_script_path):
            logger.error(f"严重错误：无法找到猫眼获取脚本 '{fetcher_script_path}'。")
            return []

        command = [
            sys.executable,
            fetcher_script_path,
            '--api-key', self.tmdb_api_key,
            '--output-file', temp_output_file,
            '--num', str(limit),
            '--platform', platform,
            '--types', *types_to_fetch
        ]
        
        try:
            logger.debug(f"  -> (在一个独立的 Greenlet 中) 执行命令: {' '.join(command)}")
            
            result_bytes = subprocess.check_output(
                command, 
                stderr=subprocess.STDOUT, 
                timeout=600
            )
            
            result_output = result_bytes.decode('utf-8', errors='ignore')
            logger.info("  -> 猫眼获取脚本成功完成。")
            if result_output:
                logger.debug(f"  -> 脚本输出:\n{result_output}")
            
            with open(temp_output_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
            
            return results

        except Timeout:
            logger.error("执行猫眼获取脚本超时（超过10分钟）。")
            return []
        except subprocess.CalledProcessError as e:
            error_output = e.output.decode('utf-8', errors='ignore') if e.output else "No output captured."
            logger.error(f"执行猫眼获取脚本失败。返回码: {e.returncode}")
            logger.error(f"  -> 脚本的完整错误输出:\n{error_output}")
            return []
        except Exception as e:
            logger.error(f"处理猫眼榜单时发生未知错误: {e}", exc_info=True)
            return []
        finally:
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)

    # ... 其他所有方法 (_match_by_ids, process, FilterEngine等) 保持完全不变 ...
    def _match_by_ids(self, imdb_id: Optional[str], tmdb_id: Optional[str], item_type: str) -> Optional[str]:
        if tmdb_id:
            logger.debug(f"通过TMDb ID直接匹配：{tmdb_id}")
            return tmdb_id
        if imdb_id:
            logger.debug(f"通过IMDb ID查找TMDb ID：{imdb_id}")
            try:
                tmdb_id_from_imdb = tmdb_handler.get_tmdb_id_by_imdb_id(imdb_id, self.tmdb_api_key, item_type)
                if tmdb_id_from_imdb:
                    logger.debug(f"IMDb ID {imdb_id} 对应 TMDb ID: {tmdb_id_from_imdb}")
                    return str(tmdb_id_from_imdb)
                else:
                    logger.warning(f"无法通过IMDb ID {imdb_id} 查找到对应的TMDb ID。")
            except Exception as e:
                logger.error(f"通过IMDb ID查找TMDb ID时出错: {e}")
        return None
    
    def _extract_ids_from_title_or_line(self, title_line: str) -> Tuple[Optional[str], Optional[str]]:
        imdb_id = None
        tmdb_id = None
        imdb_match = re.search(r'(tt\d{7,8})', title_line, re.I)
        if imdb_match:
            imdb_id = imdb_match.group(1)
        tmdb_match = re.search(r'tmdb://(\d+)', title_line, re.I)
        if tmdb_match:
            tmdb_id = tmdb_match.group(1)
        return imdb_id, tmdb_id
    
    def _get_titles_and_imdbids_from_url(self, url: str) -> List[Dict[str, str]]:
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            content = response.text
            root = ET.fromstring(content)
            items = []
            channel = root.find('channel')
            if channel is None:
                return []
            for item in channel.findall('item'):
                title_elem = item.find('title')
                guid_elem = item.find('guid')
                link_elem = item.find('link')
                title = title_elem.text if title_elem is not None else None
                imdb_id = None
                if guid_elem is not None and guid_elem.text:
                    match = re.search(r'tt\d{7,8}', guid_elem.text)
                    if match:
                        imdb_id = match.group(0)
                if not imdb_id and link_elem is not None and link_elem.text:
                    match = re.search(r'tt\d{7,8}', link_elem.text)
                    if match:
                        imdb_id = match.group(0)
                if title:
                    items.append({'title': title.strip(), 'imdb_id': imdb_id})
            return items
        except Exception as e:
            logger.error(f"从URL '{url}' 获取榜单时出错: {e}")
            return []

    def _parse_series_title(self, title: str) -> Tuple[str, Optional[int]]:
        match = self.SEASON_PATTERN.search(title)
        if not match:
            return title, None
        show_name = match.group(1).strip()
        season_word = match.group(2)
        season_number = self.CHINESE_NUM_MAP.get(season_word)
        if season_number is None:
            return title, None
        logger.debug(f"标题解析: '{title}' -> 名称='{show_name}', 季号='{season_number}'")
        return show_name, season_number

    def _match_title_to_tmdb(self, title: str, item_type: str) -> Optional[str]:
        if item_type == 'Movie':
            results = search_media(title, self.tmdb_api_key, 'Movie')
            if results:
                tmdb_id = str(results[0].get('id'))
                logger.debug(f"电影标题 '{title}' 成功匹配到: {results[0].get('title')} (ID: {tmdb_id})")
                return tmdb_id
            else:
                logger.warning(f"电影标题 '{title}' 未能在TMDb上找到匹配项。")
                return None
        elif item_type == 'Series':
            show_name, season_number_to_validate = self._parse_series_title(title)
            results = search_media(show_name, self.tmdb_api_key, 'Series')
            if not results:
                logger.warning(f"剧集标题 '{title}' (搜索词: '{show_name}') 未能在TMDb上找到匹配项。")
                return None
            series_result = results[0]
            series_id = str(series_result.get('id'))
            if season_number_to_validate is None:
                logger.debug(f"剧集标题 '{title}' 成功匹配到: {series_result.get('name')} (ID: {series_id})")
                return series_id
            logger.debug(f"剧集 '{show_name}' (ID: {series_id}) 已找到，正在验证是否存在第 {season_number_to_validate} 季...")
            series_details = get_tv_details_tmdb(int(series_id), self.tmdb_api_key, append_to_response="seasons")
            if series_details and 'seasons' in series_details:
                for season in series_details['seasons']:
                    if season.get('season_number') == season_number_to_validate:
                        logger.info(f"  -> 剧集 '{show_name}' 存在第 {season_number_to_validate} 季。最终匹配ID为 {series_id}。")
                        return series_id
            logger.warning(f"验证失败！剧集 '{show_name}' (ID: {series_id}) 存在，但未找到第 {season_number_to_validate} 季。")
            return None
        return None

    def process(self, definition: Dict) -> List[Dict[str, str]]:
        url = definition.get('url')
        if not url or url.startswith('maoyan://'):
          # 如果是猫眼URL或空URL，直接返回空列表，由上层任务处理器决定如何处理
            return []
        item_types = definition.get('item_type', ['Movie'])
        if isinstance(item_types, str):
            item_types = [item_types]
        limit = definition.get('limit')
        items = self._get_titles_and_imdbids_from_url(url)
        if not items:
            return []
        if limit and isinstance(limit, int) and limit > 0:
            logger.info(f"  -> RSS榜单已启用数量限制，将只处理前 {limit} 个项目。")
            items = items[:limit]
        tmdb_items = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            def find_first_match(item: Dict[str,str], types_to_check):
                imdb_id = item.get('imdb_id')
                title = item.get('title')
                for item_type in types_to_check:
                    tmdb_id = None
                    if imdb_id:
                        tmdb_id = self._match_by_ids(imdb_id, None, item_type)
                    if tmdb_id:
                        return {'id': tmdb_id, 'type': item_type}
                cleaned_title = re.sub(r'^\s*\d+\.\s*', '', title)
                cleaned_title = re.sub(r'\s*\(\d{4}\)$', '', cleaned_title).strip()
                for item_type in types_to_check:
                    tmdb_id = self._match_title_to_tmdb(cleaned_title, item_type)
                    if tmdb_id:
                        return {'id': tmdb_id, 'type': item_type}
                return None
            future_to_item = {executor.submit(find_first_match, item, item_types): item for item in items}
            for future in as_completed(future_to_item):
                result = future.result()
                if result:
                    tmdb_items.append(result)
        logger.info(f"  -> RSS匹配完成，成功获得 {len(tmdb_items)} 个TMDb项目。")
        unique_items = list({f"{item['type']}-{item['id']}": item for item in tmdb_items}.values())
        return unique_items

class FilterEngine:
    """
    【V3 - 功能完整最终版】负责处理 'filter' 类型的自定义合集。
    补全了对'contains'操作符的处理逻辑，确保文本筛选功能正常。
    """
    def __init__(self):
        pass

    def _item_matches_rules(self, item_metadata: Dict[str, Any], rules: List[Dict[str, Any]], logic: str) -> bool:
        if not rules: return True
        
        results = []
        for rule in rules:
            field, op, value = rule.get("field"), rule.get("operator"), rule.get("value")
            
            match = False
            
            # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            # ★ 核心修正：为不同类型的字段应用不同的列表检查逻辑 ★
            # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            
            # 1. 检查字段是否为“对象列表”（演员/导演）
            if field in ['actors', 'directors']:
                json_str = item_metadata.get(f"{field}_json")
                if json_str:
                    try:
                        # 从 '[{"id": 123, "name": "A"},...]' 中提取出所有名字
                        item_name_list = [p['name'] for p in json.loads(json_str) if 'name' in p]
                        
                        if op == 'is_one_of':
                            # 检查规则中的任何一个名字是否存在于项目的名字列表中
                            if isinstance(value, list) and any(v in item_name_list for v in value):
                                match = True
                        elif op == 'is_none_of':
                            # 检查规则中的所有名字都不存在于项目的名字列表中
                            if isinstance(value, list) and not any(v in item_name_list for v in value):
                                match = True
                        elif op == 'contains':
                            # 检查规则中的单个名字是否存在于项目的名字列表中
                            if value in item_name_list:
                                match = True
                    except (json.JSONDecodeError, TypeError):
                        pass # JSON解析失败则不匹配

            # 2. 检查字段是否为“字符串列表”（类型/国家/工作室）
            elif field in ['genres', 'countries', 'studios', 'tags']:
                json_str = item_metadata.get(f"{field}_json")
                if json_str:
                    try:
                        item_value_list = json.loads(json_str)
                        if op == 'is_one_of':
                            if isinstance(value, list) and any(v in item_value_list for v in value):
                                match = True
                        elif op == 'is_none_of':
                            if isinstance(value, list) and not any(v in item_value_list for v in value):
                                match = True
                        elif op == 'contains':
                            if value in item_value_list:
                                match = True
                    except (json.JSONDecodeError, TypeError):
                        pass

            # 3. 处理其他所有非列表字段（日期、数字等）
            elif field in ['release_date', 'date_added']:
                item_date_str = item_metadata.get(field)
                if item_date_str and str(value).isdigit():
                    try:
                        item_date = datetime.strptime(item_date_str, '%Y-%m-%d').date()
                        today = datetime.now().date()
                        days = int(value)
                        cutoff_date = today - timedelta(days=days)
                        if op == 'in_last_days':
                            if item_date >= cutoff_date and item_date <= today: match = True
                        elif op == 'not_in_last_days':
                            if item_date < cutoff_date: match = True
                    except (ValueError, TypeError): pass

            # 4：处理标题字段
            elif field == 'title':
                item_title = item_metadata.get('title')
                if item_title and isinstance(value, str):
                    # 为了不区分大小写，统一转为小写比较
                    item_title_lower = item_title.lower()
                    value_lower = value.lower()
                    
                    if op == 'contains':
                        if value_lower in item_title_lower: match = True
                    elif op == 'does_not_contain':
                        if value_lower not in item_title_lower: match = True
                    elif op == 'starts_with':
                        if item_title_lower.startswith(value_lower): match = True
                    elif op == 'ends_with':
                        if item_title_lower.endswith(value_lower): match = True
            
            else: # 处理 gte, lte, eq
                actual_item_value = item_metadata.get(field)
                if actual_item_value is not None:
                    try:
                        if op == 'gte' and float(actual_item_value) >= float(value): match = True
                        elif op == 'lte' and float(actual_item_value) <= float(value): match = True
                        elif op == 'eq' and str(actual_item_value) == str(value): match = True
                    except (ValueError, TypeError): pass

            results.append(match)

        if logic.upper() == 'AND': return all(results)
        else: return any(results)

    def execute_filter(self, definition: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        【拨乱反正最终版】根据规则，从整个媒体库中筛选出所有匹配的电影或剧集。
        此版本确保永远只返回一个纯粹的 TMDb ID 字符串列表。
        """
        logger.info("  -> 筛选引擎：开始执行全库扫描以生成合集...")
        
        rules = definition.get('rules', [])
        logic = definition.get('logic', 'AND')
        item_types_to_process = definition.get('item_type', ['Movie'])
        if isinstance(item_types_to_process, str): # 兼容旧格式
            item_types_to_process = [item_types_to_process]

        if not rules:
            logger.warning("合集定义中没有任何规则，将返回空列表。")
            return []

        matched_items = []
        # ★ 核心修改: 循环处理每种类型
        for item_type in item_types_to_process:
            all_media_metadata = db_handler.get_all_media_metadata(item_type=item_type)
            
            log_item_type_cn = "电影" if item_type == "Movie" else "电视剧"

            if not all_media_metadata:
                logger.warning(f"本地媒体元数据缓存中没有找到任何 {log_item_type_cn} 类型的项目。")
                continue # 继续检查下一种类型
            
            logger.info(f"  -> 已加载 {len(all_media_metadata)} 条{log_item_type_cn}元数据，开始应用筛选规则...")

            for media_metadata in all_media_metadata:
                if self._item_matches_rules(media_metadata, rules, logic):
                    tmdb_id = media_metadata.get('tmdb_id')
                    if tmdb_id:
                        # ★ 返回带类型信息的字典
                        matched_items.append({'id': str(tmdb_id), 'type': item_type})

        # 使用字典去重，确保 "Movie-123" 和 "Series-123" 可以共存
        unique_items = list({f"{item['type']}-{item['id']}": item for item in matched_items}.values())
        logger.info(f"  -> 筛选完成！共找到 {len(unique_items)} 部匹配的媒体项目。")
        return unique_items
    
    def find_matching_collections(self, item_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        【V2 - PG JSON 兼容版】
        为单个媒体项查找所有匹配的自定义合集。
        """
        media_item_type = item_metadata.get('item_type')
        media_type_cn = "剧集" if media_item_type == "Series" else "影片"
        
        logger.info(f"  -> 正在为{media_type_cn}《{item_metadata.get('title')}》实时匹配自定义合集...")
        matched_collections = []
        
        all_filter_collections = [
            c for c in db_handler.get_all_custom_collections() 
            if c['type'] == 'filter' and c['status'] == 'active' and c['emby_collection_id']
        ]

        if not all_filter_collections:
            logger.debug("没有发现任何已启用的筛选类合集，跳过匹配。")
            return []

        for collection_def in all_filter_collections:
            try:
                # ★★★ 核心修复：直接使用已经是字典的 definition_json 字段 ★★★
                definition = collection_def['definition_json']
                
                collection_item_types = definition.get('item_type', ['Movie'])
                
                if isinstance(collection_item_types, str):
                    collection_item_types = [collection_item_types]

                if media_item_type not in collection_item_types:
                    logger.debug(f"  -> 跳过合集《{collection_def['name']}》，因为内容类型不匹配 (合集需要: {collection_item_types}, 实际是: '{media_item_type}')。")
                    continue

                rules = definition.get('rules', [])
                logic = definition.get('logic', 'AND')

                if self._item_matches_rules(item_metadata, rules, logic):
                    logger.info(f"  -> 匹配成功！{media_type_cn}《{item_metadata.get('title')}》属于合集《{collection_def['name']}》。")
                    matched_collections.append({
                        'id': collection_def['id'],
                        'name': collection_def['name'],
                        'emby_collection_id': collection_def['emby_collection_id']
                    })
            except TypeError as e: # 捕获可能的类型错误，例如如果 definition 不是字典
                logger.warning(f"解析合集《{collection_def['name']}》的定义时出错: {e}，跳过。")
                continue
        
        return matched_collections