# services/cover_generator/__init__.py

import logging
import shutil
import yaml
import random
import requests # 使用标准的 requests 库
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# 从您的项目中导入您确认存在的模块
import config_manager
import emby_handler 

# 从我们自己的包中进行相对导入
from .styles.style_single_1 import create_style_single_1
from .styles.style_single_2 import create_style_single_2
from .styles.style_multi_1 import create_style_multi_1

# 使用标准的Python日志记录方式
logger = logging.getLogger(__name__)

class CoverGeneratorService:
    """
    一个独立的媒体库封面生成服务，从MoviePilot插件移植而来。
    """
    SORT_BY_DISPLAY_NAME = {
        "Random": "随机",
        "Latest": "最新添加"
    }
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # 从配置中解析服务设置
        self._sort_by = self.config.get("sort_by", "Random")
        self._covers_output = self.config.get("covers_output")
        self._covers_input = self.config.get("covers_input")
        self._title_config_str = self.config.get("title_config", "")
        self._cover_style = self.config.get("cover_style", "single_1")
        
        # 多图风格的特定配置
        self._multi_1_blur = self.config.get("multi_1_blur", False)
        self._multi_1_use_primary = self.config.get("multi_1_use_primary", True)
        
        # 单图风格的特定配置
        self._single_use_primary = self.config.get("single_use_primary", False)

        # 初始化路径
        self.data_path = Path(config_manager.PERSISTENT_DATA_PATH) / "cover_generator"
        self.covers_path = self.data_path / "covers"
        self.font_path = self.data_path / "fonts"
        self.covers_path.mkdir(parents=True, exist_ok=True)
        self.font_path.mkdir(parents=True, exist_ok=True)
        
        # 字体路径将在使用时动态获取
        self.zh_font_path = None
        self.en_font_path = None
        self.zh_font_path_multi_1 = None
        self.en_font_path_multi_1 = None

        self._fonts_checked_and_ready = False

    # --- 核心公开方法 ---
    def generate_for_library(self, emby_server_id: str, library: Dict[str, Any], item_count: Optional[int] = None, content_types: Optional[List[str]] = None):
        """
        为指定的媒体库生成并上传封面。
        这是从外部调用的主入口。
        ★★★ 新增 content_types 参数，用于精确指定合集内容 ★★★
        """
        sort_by_name = self.SORT_BY_DISPLAY_NAME.get(self._sort_by, self._sort_by)
        logger.info(f"  -> 开始以排序方式: {sort_by_name} 为媒体库 '{library['Name']}' 生成封面...")
        
        self.__get_fonts()

        # ★★★ 将 content_types 传递下去 ★★★
        image_data = self.__generate_image_data(emby_server_id, library, item_count, content_types)
        if not image_data:
            logger.error(f"为媒体库 '{library['Name']}' 生成封面图片失败。")
            return False

        success = self.__set_library_image(emby_server_id, library, image_data)
        if success:
            logger.info(f"  -> ✅ 成功更新媒体库 '{library['Name']}' 的封面！")
        else:
            logger.error(f"上传封面到媒体库 '{library['Name']}' 失败。")
            
        return success

    # --- 私有逻辑方法 (从原插件移植和修改) ---

    def __generate_image_data(self, server_id: str, library: Dict[str, Any], item_count: Optional[int] = None, content_types: Optional[List[str]] = None) -> bytes:
        """根据配置和媒体库内容，生成最终的封面图片二进制数据"""
        library_name = library['Name']
        title = self.__get_library_title_from_yaml(library_name)
        
        custom_image_paths = self.__check_custom_image(library_name)
        if custom_image_paths:
            logger.info(f"发现媒体库 '{library_name}' 的自定义图片，将使用路径模式生成。")
            return self.__generate_image_from_path(library_name, title, custom_image_paths, item_count)

        logger.trace(f"未发现自定义图片，将从服务器 '{server_id}' 获取媒体项作为封面来源。")
        # ★★★ 将 content_types 传递下去 ★★★
        return self.__generate_from_server(server_id, library, title, item_count, content_types)

    def __generate_from_server(self, server_id: str, library: Dict[str, Any], title: Tuple[str, str], item_count: Optional[int] = None, content_types: Optional[List[str]] = None) -> bytes:
        """从媒体服务器获取项目并生成封面"""
        required_items_count = 1 if self._cover_style.startswith('single') else 9
        
        # ★★★ 将 content_types 传递下去 ★★★
        items = self.__get_valid_items_from_library(server_id, library, required_items_count, content_types)
        if not items:
            logger.warning(f"在媒体库 '{library['Name']}' 中找不到任何带有可用图片的媒体项。")
            return None

        # 根据风格调用不同的处理函数
        if self._cover_style.startswith('single'):
            image_url = self.__get_image_url(items[0])
            if not image_url: return None
            
            image_path = self.__download_image(server_id, image_url, library['Name'], 1)
            if not image_path: return None
            
            return self.__generate_image_from_path(library['Name'], title, [image_path], item_count)
        else: # multi style
            image_paths = []
            for i, item in enumerate(items[:9]):
                image_url = self.__get_image_url(item)
                if image_url:
                    path = self.__download_image(server_id, image_url, library['Name'], i + 1)
                    if path:
                        image_paths.append(path)
            
            if not image_paths:
                logger.warning(f"为多图模式下载图片失败。")
                return None
            
            return self.__generate_image_from_path(library['Name'], title, image_paths, item_count)

    def __get_valid_items_from_library(self, server_id: str, library: Dict[str, Any], limit: int, content_types: Optional[List[str]] = None) -> List[Dict]:
        """
        【V2 - 封面生成最终修复版】
        - 优先使用外部传入的 content_types 来确定要获取的媒体类型。
        - 解决了无法获取合集(BoxSet)内部媒体项的问题。
        """
        library_id = library.get("Id") or library.get("ItemId")
        library_name = library.get("Name")
        
        base_url = config_manager.APP_CONFIG.get('emby_server_url')
        api_key = config_manager.APP_CONFIG.get('emby_api_key')
        user_id = config_manager.APP_CONFIG.get('emby_user_id')

        # --- ★★★ 核心修复：重新设计媒体类型确定逻辑 ★★★ ---
        item_types_to_fetch = None
        
        # 1. 优先使用调用者传入的精确内容类型
        if content_types:
            item_types_to_fetch = ",".join(content_types)
            logger.trace(f"  -> 使用调用者提供的精确内容类型: '{item_types_to_fetch}'")
        else:
            # 2. 如果没有传入，再回退到基于媒体库类型的猜测
            TYPE_MAP = {
                'movies': 'Movie', 'tvshows': 'Series', 'music': 'MusicAlbum',
                'boxsets': 'Movie,Series', # ★ 关键修正：合集里装的是电影和剧集
                'mixed': 'Movie,Series', 'audiobooks': 'AudioBook'
            }
            collection_type = library.get('CollectionType')
            if collection_type:
                item_types_to_fetch = TYPE_MAP.get(collection_type)
            elif library.get('Type') == 'CollectionFolder':
                item_types_to_fetch = 'Movie,Series'

        if not item_types_to_fetch:
            logger.warning(f"无法为媒体库 '{library_name}' 确定媒体类型，将使用默认值 'Movie,Series' 尝试。")
            item_types_to_fetch = 'Movie,Series'
            
        logger.trace(f"  -> 正在为媒体库 '{library_name}' 获取类型为 '{item_types_to_fetch}' 的项目...")

        all_items = emby_handler.get_emby_library_items(
            base_url=base_url,
            api_key=api_key,
            user_id=user_id,
            library_ids=[library_id],
            media_type_filter=item_types_to_fetch,
            fields="Id,Name,Type,ImageTags,BackdropImageTags,DateCreated",
            force_user_endpoint=True
        )
        
        if not all_items:
            return []
            
        valid_items = [item for item in all_items if self.__get_image_url(item)]
        
        if not valid_items:
            return []

        if self._sort_by == "Latest":
            logger.debug(f"  -> 正在对 {len(valid_items)} 个有效项目按'最新添加'进行排序...")
            valid_items.sort(key=lambda x: x.get('DateCreated', '1970-01-01T00:00:00.000Z'), reverse=True)
        elif self._sort_by == "Random":
            logger.debug(f"  -> 正在对 {len(valid_items)} 个有效项目进行'随机'排序...")
            random.shuffle(valid_items)

        return valid_items[:limit]

    def __generate_image_from_path(self, library_name: str, title: Tuple[str, str], image_paths: List[str], item_count: Optional[int] = None) -> bytes:
        """
        【字体回退修复版】使用本地图片路径列表生成封面。
        - 确保传递给底层函数的是字符串路径。
        - 在多图模式下，如果专用字体不存在，则优雅地回退到使用单图字体，并记录日志。
        """
        logger.trace(f"正在为 '{library_name}' 从本地路径生成封面...")
        
        # 字体和尺寸配置
        zh_font_size = self.config.get("zh_font_size", 1)
        en_font_size = self.config.get("en_font_size", 1)
        blur_size = self.config.get("blur_size", 50)
        color_ratio = self.config.get("color_ratio", 0.8)
        font_size = (float(zh_font_size), float(en_font_size))

        if self._cover_style == 'single_1':
            return create_style_single_1(str(image_paths[0]), title, (str(self.zh_font_path), str(self.en_font_path)), 
                                         font_size=font_size, blur_size=blur_size, color_ratio=color_ratio,
                                         item_count=item_count, config=self.config)
        
        elif self._cover_style == 'single_2':
            return create_style_single_2(str(image_paths[0]), title, (str(self.zh_font_path), str(self.en_font_path)), 
                                         font_size=font_size, blur_size=blur_size, color_ratio=color_ratio,
                                         item_count=item_count, config=self.config)
        
        elif self._cover_style == 'multi_1':
            # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            # ★ 核心修复：实现健壮的字体检查与回退逻辑 ★
            # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            
            # 检查多图专用中文字体是否存在
            if self.zh_font_path_multi_1 and self.zh_font_path_multi_1.exists():
                zh_font_path_multi = self.zh_font_path_multi_1
            else:
                logger.warning(f"未找到多图专用中文字体 ({self.zh_font_path_multi_1})，将回退使用单图字体。")
                zh_font_path_multi = self.zh_font_path

            # 检查多图专用英文字体是否存在
            if self.en_font_path_multi_1 and self.en_font_path_multi_1.exists():
                en_font_path_multi = self.en_font_path_multi_1
            else:
                logger.warning(f"未找到多图专用英文字体 ({self.en_font_path_multi_1})，将回退使用单图字体。")
                en_font_path_multi = self.en_font_path

            # 最终组合要使用的字体路径
            font_path_multi = (str(zh_font_path_multi), str(en_font_path_multi))
            
            zh_font_size_multi = self.config.get("zh_font_size_multi_1", 1)
            en_font_size_multi = self.config.get("en_font_size_multi_1", 1)
            font_size_multi = (float(zh_font_size_multi), float(en_font_size_multi))
            
            blur_size_multi = self.config.get("blur_size_multi_1", 50)
            color_ratio_multi = self.config.get("color_ratio_multi_1", 0.8)

            library_dir = self.covers_path / library_name
            self.__prepare_multi_images(library_dir, image_paths)
            
            return create_style_multi_1(str(library_dir), title, font_path_multi, 
                                      font_size=font_size_multi, 
                                      is_blur=self._multi_1_blur, 
                                      blur_size=blur_size_multi, 
                                      color_ratio=color_ratio_multi,
                                      item_count=item_count, config=self.config)
        return None

    def __set_library_image(self, server_id: str, library: Dict[str, Any], image_data: bytes) -> bool:
        """上传封面到媒体库"""
        library_id = library.get("Id") or library.get("ItemId")
        
        base_url = config_manager.APP_CONFIG.get('emby_server_url')
        api_key = config_manager.APP_CONFIG.get('emby_api_key')
        
        upload_url = f"{base_url.rstrip('/')}/Items/{library_id}/Images/Primary?api_key={api_key}"
        headers = {"Content-Type": "image/jpeg"}

        if self._covers_output:
            try:
                save_path = Path(self._covers_output) / f"{library['Name']}.jpg"
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(image_data)
                logger.info(f"封面已另存到: {save_path}")
            except Exception as e:
                logger.error(f"另存封面失败: {e}")

        try:
            response = requests.post(upload_url, data=image_data, headers=headers, timeout=30)
            response.raise_for_status()
            logger.debug(f"  -> 成功上传封面到媒体库 '{library['Name']}'。")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"上传封面到媒体库 '{library['Name']}' 时发生网络错误: {e}")
            if e.response is not None:
                logger.error(f"  -> 响应状态: {e.response.status_code}, 响应内容: {e.response.text[:200]}")
            return False

    # --- 以下是辅助函数 ---

    def __get_library_title_from_yaml(self, library_name: str) -> Tuple[str, str]:
        zh_title, en_title = library_name, ''
        if not self._title_config_str:
            return zh_title, en_title
        try:
            title_config = yaml.safe_load(self._title_config_str)
            if isinstance(title_config, dict) and library_name in title_config:
                titles = title_config[library_name]
                if isinstance(titles, list) and len(titles) >= 2:
                    zh_title, en_title = titles[0], titles[1]
        except yaml.YAMLError as e:
            logger.error(f"解析标题配置失败: {e}")
        return zh_title, en_title

    def __get_image_url(self, item: Dict[str, Any]) -> str:
        item_id = item.get("Id")
        if self._cover_style.startswith('single') and not self._single_use_primary:
            if item.get("BackdropImageTags"):
                return f'/emby/Items/{item_id}/Images/Backdrop/0?tag={item["BackdropImageTags"][0]}'
        if item.get("ImageTags", {}).get("Primary"):
            return f'/emby/Items/{item_id}/Images/Primary?tag={item["ImageTags"]["Primary"]}'
        if item.get("BackdropImageTags"):
            return f'/emby/Items/{item_id}/Images/Backdrop/0?tag={item["BackdropImageTags"][0]}'
        return None

    def __download_image(self, server_id: str, api_path: str, library_name: str, count: int) -> Path:
        subdir = self.covers_path / library_name
        subdir.mkdir(parents=True, exist_ok=True)
        filepath = subdir / f"{count}.jpg"
        
        try:
            base_url = config_manager.APP_CONFIG.get('emby_server_url')
            api_key = config_manager.APP_CONFIG.get('emby_api_key')

            path_parts = api_path.strip('/').split('/')
            if len(path_parts) >= 4 and path_parts[1] == 'Items' and path_parts[3] == 'Images':
                item_id = path_parts[2]
                image_type = path_parts[4].split('?')[0]

                success = emby_handler.download_emby_image(
                    item_id=item_id,
                    image_type=image_type,
                    save_path=str(filepath),
                    emby_server_url=base_url,
                    emby_api_key=api_key
                )
                
                if success:
                    return filepath
            else:
                logger.error(f"无法从API路径解析有效的项目ID和图片类型: {api_path}")

        except Exception as e:
            logger.error(f"下载图片失败 ({api_path}): {e}", exc_info=True)
            
        return None
        
    def __prepare_multi_images(self, library_dir: Path, source_paths: List[str]):
        """为多图模式准备9张图片"""
        library_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, 10):
            target_path = library_dir / f"{i}.jpg"
            if not target_path.exists():
                source_to_copy = random.choice(source_paths)
                shutil.copy(source_to_copy, target_path)

    def __check_custom_image(self, library_name: str) -> List[str]:
        if not self._covers_input: return []
        library_dir = Path(self._covers_input) / library_name
        if not library_dir.is_dir(): return []
        images = sorted([
            str(p) for p in library_dir.iterdir()
            if p.suffix.lower() in [".jpg", ".jpeg", ".png"]
        ])
        return images

    def __download_file(self, url: str, dest_path: Path):
        """下载文件到指定路径，如果文件已存在则跳过。"""
        if dest_path.exists():
            logger.trace(f"字体文件已存在，跳过下载: {dest_path.name}")
            return
        
        logger.info(f"字体文件不存在，正在从URL下载: {dest_path.name}...")
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"字体 '{dest_path.name}' 下载成功。")
        except requests.RequestException as e:
            logger.error(f"下载字体 '{dest_path.name}' 失败: {e}")
            # 如果下载失败，可以考虑删除不完整的文件
            if dest_path.exists():
                dest_path.unlink()

    def __get_fonts(self):
        """
        检查并准备字体文件。此函数只会完整运行一次。
        它会优先检查最终的字体文件是否存在，如果存在则直接使用，
        只有在文件不存在时，才会去解析配置并尝试下载。
        """
        if self._fonts_checked_and_ready:
            return

        font_definitions = [
            {"target_attr": "zh_font_path", "filename": "zh_font.ttf", "local_key": "zh_font_path_local", "url_key": "zh_font_url"},
            {"target_attr": "en_font_path", "filename": "en_font.ttf", "local_key": "en_font_path_local", "url_key": "en_font_url"},
            {"target_attr": "zh_font_path_multi_1", "filename": "zh_font_multi_1.ttf", "local_key": "zh_font_path_multi_1_local", "url_key": "zh_font_url_multi_1"},
            {"target_attr": "en_font_path_multi_1", "filename": "en_font_multi_1.otf", "local_key": "en_font_path_multi_1_local", "url_key": "en_font_url_multi_1"}
        ]

        for font_def in font_definitions:
            font_path_to_set = None
            
            # 步骤 A: 检查预设的本地字体文件是否存在
            expected_font_file = self.font_path / font_def["filename"]
            if expected_font_file.exists():
                font_path_to_set = expected_font_file
            
            # 步骤 B: 检查用户是否在UI中指定了外部的本地路径
            local_path_str = self.config.get(font_def["local_key"])
            if local_path_str:
                local_path = Path(local_path_str)
                if local_path.exists():
                    logger.trace(f"发现并优先使用用户指定的外部字体: {local_path_str}")
                    font_path_to_set = local_path
                else:
                    logger.warning(f"配置的外部字体路径不存在: {local_path_str}，将忽略此配置。")

            # 步骤 C: 如果以上路径都无效，且文件确实不存在，才尝试从URL下载
            if not font_path_to_set:
                url = self.config.get(font_def["url_key"])
                if url:
                    self.__download_file(url, expected_font_file)
                    if expected_font_file.exists():
                        font_path_to_set = expected_font_file
            
            # 将最终确定的有效路径设置到实例属性上
            setattr(self, font_def["target_attr"], font_path_to_set)

        # 最后，统一检查核心字体是否就绪，并设置“记忆”标志
        if self.zh_font_path and self.en_font_path:
            logger.trace("核心字体文件已准备就绪。后续任务将不再重复检查。")
            self._fonts_checked_and_ready = True # 大功告成，设置标志为True
        else:
            # 只有在所有努力都失败后，才打印一次真正的警告
            logger.warning("一个或多个核心字体文件缺失且无法下载。请检查UI中的本地路径或下载链接是否有效。")