# custom_collection_handler.py
import logging
import requests
import xml.etree.ElementTree as ET
import re
import os
import sys
from typing import List, Dict, Any, Optional, Tuple
import json
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed

# ★★★ 核心修正：再次回归 gevent.subprocess ★★★
from gevent import subprocess, Timeout

import tmdb_handler
import emby_handler
import config_manager
import db_handler 
from douban import DoubanApi
from tmdb_handler import search_media, get_tv_details_tmdb

logger = logging.getLogger(__name__)


class ListImporter:
    """
    (V9.1 - 最终异步版)
    使用 gevent.subprocess，并确保在独立的 greenlet 中运行，
    从而实现真正的非阻塞异步执行。
    """
    
    SEASON_PATTERN = re.compile(r'(.*?)\s*[（(]?\s*(第?[一二三四五六七八九十百]+)\s*季\s*[)）]?')
    
    # ▼▼▼ 优化：扩展数字映射，支持到二十季，增强兼容性 ▼▼▼
    CHINESE_NUM_MAP = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15, '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20,
        '第一': 1, '第二': 2, '第三': 3, '第四': 4, '第五': 5, '第六': 6, '第七': 7, '第八': 8, '第九': 9, '第十': 10,
        '第十一': 11, '第十二': 12, '第十三': 13, '第十四': 14, '第十五': 15, '第十六': 16, '第十七': 17, '第十八': 18, '第十九': 19, '第二十': 20
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
            if channel is None: return []
            for item in channel.findall('item'):
                title_elem = item.find('title')
                guid_elem = item.find('guid')
                link_elem = item.find('link')
                description_elem = item.find('description')
                
                title = title_elem.text if title_elem is not None else None
                description = description_elem.text if description_elem is not None else ''
                
                # ✨ 新增：获取豆瓣链接 ✨
                douban_link = None
                if link_elem is not None and link_elem.text and 'douban.com' in link_elem.text:
                    douban_link = link_elem.text
                elif guid_elem is not None and guid_elem.text and 'douban.com' in guid_elem.text:
                    douban_link = guid_elem.text

                year = None
                year_match = re.search(r'\b(20\d{2})\b', description)
                if year_match: year = year_match.group(1)

                imdb_id = None
                if guid_elem is not None and guid_elem.text:
                    match = re.search(r'tt\d{7,8}', guid_elem.text)
                    if match: imdb_id = match.group(0)
                if not imdb_id and link_elem is not None and link_elem.text:
                    match = re.search(r'tt\d{7,8}', link_elem.text)
                    if match: imdb_id = match.group(0)
                
                if title:
                    items.append({'title': title.strip(), 'imdb_id': imdb_id, 'year': year, 'douban_link': douban_link})
            return items
        except Exception as e:
            logger.error(f"从URL '{url}' 获取榜单时出错: {e}")
            return []

    def _parse_series_title(self, title: str) -> Tuple[str, Optional[int]]:
        # 新增：支持 "Name Season 2" 格式的英文正则，忽略大小写
        SEASON_PATTERN_EN = re.compile(r'(.*?)\s+Season\s+(\d+)', re.IGNORECASE)
        
        # 优先尝试匹配英文格式
        match_en = SEASON_PATTERN_EN.search(title)
        if match_en:
            show_name = match_en.group(1).strip()
            season_number = int(match_en.group(2))
            logger.debug(f"标题解析 (英文): '{title}' -> 名称='{show_name}', 季号='{season_number}'")
            return show_name, season_number

        # 如果英文匹配失败，再尝试中文格式
        match_cn = self.SEASON_PATTERN.search(title)
        if not match_cn:
            return title, None # 中英文都匹配不上，返回原标题
        
        show_name = match_cn.group(1).strip()
        season_word = match_cn.group(2)
        season_number = self.CHINESE_NUM_MAP.get(season_word)
        if season_number is None:
            return title, None
            
        logger.debug(f"标题解析 (中文): '{title}' -> 名称='{show_name}', 季号='{season_number}'")
        return show_name, season_number

    def _match_title_to_tmdb(self, title: str, item_type: str, year: Optional[str] = None) -> Optional[str]:
        if item_type == 'Movie':
            results = search_media(title, self.tmdb_api_key, 'Movie', year=year)
            year_info = f" (年份: {year})" if year else ""

            if not results:
                logger.warning(f"电影标题 '{title}'{year_info} 未能在TMDb上找到任何搜索结果。")
                return None

            # ★★★ 核心修复：从“盲目相信第一个”改为“优先精确匹配” ★★★

            # 步骤 1: 优先寻找标题完全一致的精确匹配项
            normalized_title = title.strip().lower()
            for result in results:
                result_title = result.get('title', '').strip().lower()
                result_original_title = result.get('original_title', '').strip().lower()

                if result_title == normalized_title or result_original_title == normalized_title:
                    tmdb_id = str(result.get('id'))
                    logger.debug(f"电影标题 '{title}'{year_info} 通过【精确匹配】成功匹配到: {result.get('title')} (ID: {tmdb_id})")
                    return tmdb_id

            # 步骤 2: 如果没有找到精确匹配，则回退使用第一个最相关的结果，并发出警告
            first_result = results[0]
            tmdb_id = str(first_result.get('id'))
            logger.warning(f"电影标题 '{title}'{year_info} 未找到精确匹配项。将【回退使用】最相关的搜索结果: {first_result.get('title')} (ID: {tmdb_id})")
            return tmdb_id
        
        elif item_type == 'Series':
            show_name, season_number_to_validate = self._parse_series_title(title)
            
            results = search_media(show_name, self.tmdb_api_key, 'Series', year=year)

            if not results and year and season_number_to_validate is not None:
                logger.debug(f"带年份 '{year}' 搜索剧集 '{show_name}' 未找到结果，可能是后续季。尝试不带年份进行回退搜索...")
                results = search_media(show_name, self.tmdb_api_key, 'Series', year=None)

            if not results:
                year_info = f" (年份: {year})" if year else ""
                logger.warning(f"剧集标题 '{title}' (搜索词: '{show_name}'){year_info} 未能在TMDb上找到匹配项。")
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
            return []
        item_types = definition.get('item_type', ['Movie'])
        if isinstance(item_types, str): item_types = [item_types]
        limit = definition.get('limit')
        items = self._get_titles_and_imdbids_from_url(url)
        if not items: return []
        if limit and isinstance(limit, int) and limit > 0:
            logger.info(f"  -> RSS榜单已启用数量限制，将只处理前 {limit} 个项目。")
            items = items[:limit]
        
        tmdb_items = []
        douban_api = DoubanApi()

        with ThreadPoolExecutor(max_workers=5) as executor:
            def find_first_match(item: Dict[str, str], types_to_check):
                title = item.get('title')
                year = item.get('year')
                rss_imdb_id = item.get('imdb_id')
                douban_link = item.get('douban_link')

                cleaned_title_for_parsing = re.sub(r'^\s*\d+\.\s*', '', title)
                cleaned_title_for_parsing = re.sub(r'\s*\(\d{4}\)$', '', cleaned_title_for_parsing).strip()
                _, season_number = self._parse_series_title(cleaned_title_for_parsing)

                def create_result(tmdb_id, item_type):
                    result = {'id': tmdb_id, 'type': item_type}
                    if item_type == 'Series' and season_number is not None:
                        logger.debug(f"  -> 为剧集 '{title}' 附加季号: {season_number}")
                        result['season'] = season_number
                    return result

                if rss_imdb_id:
                    for item_type in types_to_check:
                        tmdb_id = self._match_by_ids(rss_imdb_id, None, item_type)
                        if tmdb_id:
                            logger.info(f"  -> 成功通过RSS自带的IMDb ID '{rss_imdb_id}' 匹配到 '{title}'。")
                            return create_result(tmdb_id, item_type)

                cleaned_title = re.sub(r'^\s*\d+\.\s*', '', title)
                cleaned_title = re.sub(r'\s*\(\d{4}\)$', '', cleaned_title).strip()
                for item_type in types_to_check:
                    tmdb_id = self._match_title_to_tmdb(cleaned_title, item_type, year=year)
                    if tmdb_id:
                        return create_result(tmdb_id, item_type)
                
                if douban_link:
                    logger.info(f"  -> 片名+年份匹配 '{title}' 失败，启动备用方案：通过豆瓣链接获取更多信息...")
                    douban_details = douban_api.get_details_from_douban_link(douban_link, mtype=types_to_check[0] if types_to_check else None)
                    
                    if douban_details:
                        imdb_id_from_douban = douban_details.get("imdb_id")
                        if not imdb_id_from_douban and douban_details.get("attrs", {}).get("imdb"):
                            imdb_ids = douban_details["attrs"]["imdb"]
                            if isinstance(imdb_ids, list) and len(imdb_ids) > 0:
                                imdb_id_from_douban = imdb_ids[0]

                        if imdb_id_from_douban:
                            logger.info(f"  -> 豆瓣备用方案(3a)成功！拿到IMDb ID: {imdb_id_from_douban}，现在用它匹配TMDb...")
                            for item_type in types_to_check:
                                tmdb_id = self._match_by_ids(imdb_id_from_douban, None, item_type)
                                if tmdb_id:
                                    return create_result(tmdb_id, item_type)
                        
                        logger.info(f"  -> 豆瓣备用方案(3a)失败，尝试方案(3b): 使用 original_title...")
                        original_title = douban_details.get("original_title")
                        if original_title:
                            for item_type in types_to_check:
                                tmdb_id = self._match_title_to_tmdb(original_title, item_type, year=year)
                                if tmdb_id:
                                    logger.info(f"  -> 豆瓣备用方案(3b)成功！通过 original_title '{original_title}' 匹配成功。")
                                    return create_result(tmdb_id, item_type)

                logger.debug(f"  -> 所有优先方案均失败，尝试不带年份进行最后的回退搜索: '{title}'")
                for item_type in types_to_check:
                    tmdb_id = self._match_title_to_tmdb(cleaned_title, item_type, year=None)
                    if tmdb_id:
                        logger.warning(f"  -> 注意：'{title}' 在最后的回退搜索中匹配成功，但年份可能不准。")
                        return create_result(tmdb_id, item_type)

                logger.error(f"  -> 彻底失败：所有方案都无法为 '{title}' 找到匹配项。")
                return None

            # ★★★ 核心修复：使用 executor.map 替换 as_completed 来保证顺序 ★★★
            # executor.map 会并发处理，但会按照输入 `items` 的原始顺序返回结果。
            results_in_order = executor.map(lambda item: find_first_match(item, item_types), items)
            
            # 过滤掉那些匹配失败返回 None 的结果
            tmdb_items = [result for result in results_in_order if result is not None]
        
        douban_api.close()
        logger.info(f"  -> RSS匹配完成，成功获得 {len(tmdb_items)} 个TMDb项目。")
        
        unique_items = list({f"{item['type']}-{item['id']}-{item.get('season')}": item for item in tmdb_items}.values())
        return unique_items

class FilterEngine:
    """
    【V4 - PG JSON 兼容最终版】
    - 修复了 _item_matches_rules 方法中因 psycopg2 自动解析 JSON 字段而导致的 TypeError。
    - 移除了所有对 _json 字段的多余 json.loads() 调用，解决了筛选规则静默失效的问题。
    """
    def __init__(self):
        pass

    def _item_matches_rules(self, item_metadata: Dict[str, Any], rules: List[Dict[str, Any]], logic: str) -> bool:
        if not rules: return True
        
        results = []
        for rule in rules:
            field, op, value = rule.get("field"), rule.get("operator"), rule.get("value")
            match = False
            
            # 1. 检查字段是否为“对象列表”（演员/导演）
            if field in ['actors', 'directors']:
                # ★★★ 核心修复 1/2：直接使用已经是列表的 _json 字段 ★★★
                item_object_list = item_metadata.get(f"{field}_json")
                if item_object_list:
                    try:
                        # 不再需要 json.loads()
                        item_name_list = [p['name'] for p in item_object_list if 'name' in p]
                        
                        if op == 'is_one_of':
                            if isinstance(value, list) and any(v in item_name_list for v in value):
                                match = True
                        elif op == 'is_none_of':
                            if isinstance(value, list) and not any(v in item_name_list for v in value):
                                match = True
                        elif op == 'contains':
                            if value in item_name_list:
                                match = True
                    except TypeError:
                        # 增加保护，以防万一某行数据格式真的有问题
                        logger.warning(f"处理 {field}_json 时遇到意外的类型错误，内容: {item_object_list}")

            # 2. 检查字段是否为“字符串列表”（类型/国家/工作室/标签）
            elif field in ['genres', 'countries', 'studios', 'tags']:
                # ★★★ 核心修复 2/2：直接使用已经是列表的 _json 字段 ★★★
                item_value_list = item_metadata.get(f"{field}_json")
                if item_value_list:
                    try:
                        # 不再需要 json.loads()
                        if op == 'is_one_of':
                            if isinstance(value, list) and any(v in item_value_list for v in value):
                                match = True
                        elif op == 'is_none_of':
                            if isinstance(value, list) and not any(v in item_value_list for v in value):
                                match = True
                        elif op == 'contains':
                            if value in item_value_list:
                                match = True
                    except TypeError:
                        logger.warning(f"处理 {field}_json 时遇到意外的类型错误，内容: {item_value_list}")

            # 3. 处理其他所有非列表字段 (这部分逻辑是正确的，无需修改)
            elif field in ['release_date', 'date_added']:
                item_date_val = item_metadata.get(field)
                if item_date_val and str(value).isdigit():
                    try:
                        # 兼容处理 datetime 和 date 类型
                        if isinstance(item_date_val, datetime):
                            item_date = item_date_val.date()
                        elif isinstance(item_date_val, date):
                            item_date = item_date_val
                        else:
                            # 兼容字符串格式
                            item_date = datetime.strptime(str(item_date_val), '%Y-%m-%d').date()

                        today = datetime.now().date()
                        days = int(value)
                        cutoff_date = today - timedelta(days=days)

                        if op == 'in_last_days':
                            if cutoff_date <= item_date <= today:
                                match = True
                        elif op == 'not_in_last_days':
                            if item_date < cutoff_date:
                                match = True
                    except (ValueError, TypeError):
                        pass

            # 4. 处理分级字段
            elif field == 'unified_rating':
                item_unified_rating = item_metadata.get('unified_rating')
                if item_unified_rating:
                    if op == 'is_one_of':
                        if isinstance(value, list) and item_unified_rating in value:
                            match = True
                    elif op == 'is_none_of':
                        if isinstance(value, list) and item_unified_rating not in value:
                            match = True
                    elif op == 'eq':
                        if str(value) == item_unified_rating:
                            match = True

            elif field == 'title':
                item_title = item_metadata.get('title')
                if item_title and isinstance(value, str):
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
            
            else:
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
        logger.info("  -> 筛选引擎：开始执行合集生成...")
        rules = definition.get('rules', [])
        logic = definition.get('logic', 'AND')
        item_types_to_process = definition.get('item_type', ['Movie'])
        if isinstance(item_types_to_process, str):
            item_types_to_process = [item_types_to_process]
        if not rules:
            logger.warning("合集定义中没有任何规则，将返回空列表。")
            return []

        # ★★★ 核心修改：根据定义判断数据源 ★★★
        library_ids = definition.get('library_ids')
        all_media_metadata = []

        if library_ids and isinstance(library_ids, list) and len(library_ids) > 0:
            # --- 分支1：从指定的媒体库加载数据 ---
            logger.info(f"  -> 已指定 {len(library_ids)} 个媒体库作为筛选范围。")
            
            # 从配置中获取Emby连接信息
            cfg = config_manager.APP_CONFIG
            emby_url = cfg.get('emby_server_url')
            emby_key = cfg.get('emby_api_key')
            emby_user_id = cfg.get('emby_user_id')

            if not all([emby_url, emby_key, emby_user_id]):
                logger.error("Emby服务器配置不完整，无法从指定媒体库筛选。")
                return []

            # 1. 从指定的Emby库中获取所有媒体项
            emby_items = emby_handler.get_emby_library_items(
                base_url=emby_url,
                api_key=emby_key,
                user_id=emby_user_id,
                library_ids=library_ids,
                media_type_filter=",".join(item_types_to_process)
            )

            if not emby_items:
                logger.warning("从指定的媒体库中未能获取到任何媒体项。")
                return []

            # 2. 提取这些媒体项的TMDb ID
            tmdb_ids_from_libs = [
                item['ProviderIds']['Tmdb']
                for item in emby_items
                if item.get('ProviderIds', {}).get('Tmdb')
            ]

            if not tmdb_ids_from_libs:
                logger.warning("指定媒体库中的项目均缺少TMDb ID，无法进行筛选。")
                return []
            
            # 3. 根据TMDb ID列表，从我们的数据库缓存中批量获取元数据
            logger.info(f"  -> 正在从本地缓存中查询这 {len(tmdb_ids_from_libs)} 个项目的元数据...")
            for item_type in item_types_to_process:
                metadata_for_type = db_handler.get_media_metadata_by_tmdb_ids(tmdb_ids_from_libs, item_type)
                all_media_metadata.extend(metadata_for_type)

        else:
            # --- 分支2：保持原有逻辑，扫描全库 ---
            logger.info("  -> 未指定媒体库，将扫描所有媒体库的元数据缓存...")
            for item_type in item_types_to_process:
                all_media_metadata.extend(db_handler.get_all_media_metadata(item_type=item_type))

        # --- 后续的筛选逻辑保持不变 ---
        matched_items = []
        if not all_media_metadata:
            logger.warning("未能加载任何媒体元数据进行筛选。")
            return []
        
        logger.info(f"  -> 已加载 {len(all_media_metadata)} 条元数据，开始应用筛选规则...")
        for media_metadata in all_media_metadata:
            if self._item_matches_rules(media_metadata, rules, logic):
                tmdb_id = media_metadata.get('tmdb_id')
                item_type = media_metadata.get('item_type')
                if tmdb_id and item_type:
                    matched_items.append({'id': str(tmdb_id), 'type': item_type})
                    
        unique_items = list({f"{item['type']}-{item['id']}": item for item in matched_items}.values())
        logger.info(f"  -> 筛选完成！共找到 {len(unique_items)} 部匹配的媒体项目。")
        return unique_items
    
    def find_matching_collections(self, item_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
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
            except TypeError as e:
                logger.warning(f"解析合集《{collection_def['name']}》的定义时出错: {e}，跳过。")
                continue
        return matched_collections
    
    # ▼▼▼ 动态筛选 ▼▼▼
    def _item_matches_dynamic_rules(self, emby_item: Dict[str, Any], rules: List[Dict[str, Any]], logic: str) -> bool:
        if not rules: return True
        
        results = []
        user_data = emby_item.get('UserData', {})

        for rule in rules:
            field, op, value = rule.get("field"), rule.get("operator"), rule.get("value")
            match = False
            
            # 默认操作符为 'is'，以兼容旧数据
            if not op: op = 'is'

            if field == 'playback_status':
                current_status = 'unplayed'  # 默认状态
                item_type = emby_item.get('Type')

                # ★★★ 核心修改：针对剧集的优化逻辑 ★★★
                if item_type == 'Series':
                    unplayed_count = user_data.get('UnplayedItemCount')
                    total_count = emby_item.get('RecursiveItemCount')

                    # 只有在能获取到有效数据时才使用新逻辑
                    if unplayed_count is not None and total_count is not None and total_count > 0:
                        if unplayed_count == 0:
                            current_status = 'played'
                        elif unplayed_count < total_count:
                            current_status = 'in_progress'
                        else:  # unplayed_count >= total_count
                            current_status = 'unplayed'
                    else:
                        # 如果数据不完整，回退到旧的、基于整体Played状态的判断
                        is_played = user_data.get('Played', False)
                        if is_played:
                            current_status = 'played'
                        # 注意：剧集的 PlaybackPositionTicks 不可靠，这里不判断 in_progress

                # ★★★ 电影和其他类型的回退逻辑 (保持旧逻辑不变) ★★★
                else:
                    is_played = user_data.get('Played', False)
                    in_progress = user_data.get('PlaybackPositionTicks', 0) > 0
                    
                    if is_played:
                        current_status = 'played'
                    elif in_progress:
                        current_status = 'in_progress'
                    # else 默认是 unplayed

                # 后续的 is_match 和 op 判断逻辑保持不变
                is_match = (current_status == value)
                
                if op == 'is':
                    match = is_match
                elif op == 'is_not':
                    match = not is_match

            elif field == 'is_favorite':
                is_favorite = user_data.get('IsFavorite', False)
                
                # 先判断是否“是”
                is_match = (value is True and is_favorite) or \
                           (value is False and not is_favorite)
                
                # 再根据操作符决定最终结果
                if op == 'is':
                    match = is_match
                elif op == 'is_not':
                    match = not is_match
            
            results.append(match)

        # 动态筛选目前只支持 AND
        return all(results)

    def execute_dynamic_filter(self, all_emby_items: List[Dict[str, Any]], definition: Dict[str, Any]) -> List[Dict[str, Any]]:
        logger.trace("  -> 动态筛选引擎：开始在实时数据上执行规则...")
        rules = definition.get('rules', [])
        logic = definition.get('logic', 'AND')
        
        if not rules:
            return all_emby_items

        matched_items = [item for item in all_emby_items if self._item_matches_dynamic_rules(item, rules, logic)]
        
        logger.trace(f"  -> 动态筛选完成！共找到 {len(matched_items)} 部匹配的媒体项目。")
        return matched_items