<!-- src/components/ResubscribePage.vue -->
<template>
  <n-layout content-style="padding: 24px;">
    <div class="resubscribe-page">
      <n-page-header>
        <template #title>
          <n-space align="center">
            <span>媒体洗版</span>
            <!-- 总数现在从 allItems 中获取 -->
            <n-tag v-if="allItems.length > 0" type="info" round :bordered="false" size="small">
              {{ allItems.length }} 项
            </n-tag>
          </n-space>
        </template>
        <n-alert title="操作提示" type="info" style="margin-top: 24px;">
          先进行洗版规则设定，然后点击刷新按钮扫描全库媒体项，扫描完刷新页面会展示所有媒体项并按照预设的洗版规则显示是否需要洗版。<br />
          需洗版的订阅后会转为已订阅的状态，下次刷新时如果已重新下载并入库会转换状态成质量达标。
        </n-alert>
        <template #extra>
          <n-space>
            <n-radio-group v-model:value="filter" size="small">
              <n-radio-button value="all">全部</n-radio-button>
              <n-radio-button value="needed">需洗版</n-radio-button>
            </n-radio-group>
            <n-button @click="showSettingsModal = true">洗版规则设定</n-button>
            <n-button type="warning" @click="triggerResubscribeAll" :loading="isTaskRunning('全库媒体洗版')">一键洗版全部</n-button>
            <n-button type="primary" @click="triggerRefreshStatus" :loading="isTaskRunning('刷新媒体洗版状态')" circle>
              <template #icon><n-icon :component="SyncOutline" /></template>
            </n-button>
          </n-space>
        </template>
      </n-page-header>
      <n-divider />

      <div v-if="isLoading" class="center-container"><n-spin size="large" /></div>
      <div v-else-if="error" class="center-container"><n-alert title="加载错误" type="error">{{ error }}</n-alert></div>
      <!-- ★★★ 核心修改 1/3: v-for 现在遍历 displayedItems ★★★ -->
      <div v-else-if="displayedItems.length > 0">
        <n-grid cols="1 s:1 m:2 l:3 xl:4" :x-gap="20" :y-gap="20" responsive="screen">
          <n-gi v-for="item in displayedItems" :key="item.item_id">
            <n-card class="dashboard-card series-card" :bordered="false">
              <!-- 卡片内部结构保持不变 -->
              <div class="card-poster-container">
                <n-image lazy :src="getPosterUrl(item.item_id)" class="card-poster" object-fit="cover" />
              </div>
              <div class="card-content-container">
                <div class="card-header">
                  <n-ellipsis class="card-title">{{ item.item_name }}</n-ellipsis>
                </div>
                <div class="card-status-area">
                  <n-space vertical size="small">
                    <n-tag :type="getStatusInfo(item.status).type" size="small">
                      {{ getStatusInfo(item.status).text }}
                    </n-tag>
                    <div>
                      <!-- 当需要显示原因时，正常渲染 -->
                      <n-tooltip v-if="item.status === 'needed'">
                        <template #trigger>
                          <n-text :depth="3" class="reason-text" :line-clamp="2">
                            原因: {{ item.reason }}
                          </n-text>
                        </template>
                        {{ item.reason }}
                      </n-tooltip>
                      <!-- 否则，渲染一个具有相同样式但隐形的占位符来撑开高度 -->
                      <n-text v-else :depth="3" class="reason-text" :line-clamp="2" style="visibility: hidden;">
                        占位
                      </n-text>
                    </div>
                    <n-divider style="margin: 4px 0;" />
                    <n-text :depth="2" class="info-text">分辨率: {{ item.resolution_display }}</n-text>
                    <n-text :depth="2" class="info-text">质量: {{ item.quality_display }}</n-text>
                    <n-text :depth="2" class="info-text">特效: {{ item.effect_display }}</n-text>
                    <n-tooltip>
                      <template #trigger><n-text :depth="2" class="info-text" :line-clamp="1">音轨: {{ item.audio_display }}</n-text></template>
                      {{ item.audio_display }}
                    </n-tooltip>
                    <n-tooltip>
                      <template #trigger><n-text :depth="2" class="info-text" :line-clamp="1">字幕: {{ item.subtitle_display }}</n-text></template>
                      {{ item.subtitle_display }}
                    </n-tooltip>
                  </n-space>
                </div>
                <div class="card-actions">
                  <n-button v-if="item.status === 'needed'" size="small" type="primary" @click="resubscribeItem(item)" :loading="subscribing[item.item_id]">
                    洗版订阅
                  </n-button>
                  <n-button v-else-if="item.status === 'subscribed'" size="small" type="info" disabled>
                    已订阅
                  </n-button>
                  <n-button v-else size="small" style="visibility: hidden;">
                    占位按钮
                  </n-button>
                  <n-button text @click="openInEmby(item.item_id)"><template #icon><n-icon :component="EmbyIcon" size="18" /></template></n-button>
                  <n-button text tag="a" :href="`https://www.themoviedb.org/${item.item_type === 'Movie' ? 'movie' : 'tv'}/${item.tmdb_id}`" target="_blank"><template #icon><n-icon :component="TMDbIcon" size="18" /></template></n-button>
                </div>
              </div>
            </n-card>
          </n-gi>
        </n-grid>
        <!-- ★★★ 核心修改 2/3: 添加“哨兵”元素和加载动画 ★★★ -->
        <div ref="loaderTrigger" class="loader-trigger">
          <!-- 只有在还有更多数据可加载时才显示 Spin -->
          <n-spin v-if="displayedItems.length < filteredItems.length" />
        </div>
      </div>
      <div v-else class="center-container"><n-empty description="缓存为空，请点击右上角刷新按钮来扫描媒体库。" size="huge" /></div>
    </div>

    <n-modal v-model:show="showSettingsModal" preset="card" style="width: 90%; max-width: 800px;" title="洗版规则设定">
      <ResubscribeSettingsPage @saved="showSettingsModal = false" />
    </n-modal>
  </n-layout>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, h, watch, nextTick } from 'vue'; // 引入 nextTick 和 onUnmounted
import axios from 'axios';
import { NLayout, NPageHeader, NDivider, NEmpty, NTag, NButton, NSpace, NIcon, useMessage, NGrid, NGi, NCard, NImage, NEllipsis, NSpin, NAlert, NRadioGroup, NRadioButton, NModal, NTooltip, NText } from 'naive-ui';
import { SyncOutline } from '@vicons/ionicons5';
import { useConfig } from '../composables/useConfig.js';
import ResubscribeSettingsPage from './settings/ResubscribeSettingsPage.vue';

// ... (Icon 定义保持不变) ...
const EmbyIcon = () => h('svg', { xmlns: "http://www.w.org/2000/svg", viewBox: "0 0 48 48", width: "18", height: "18" }, [ h('path', { d: "M24,4.2c-11,0-19.8,8.9-19.8,19.8S13,43.8,24,43.8s19.8-8.9,19.8-19.8S35,4.2,24,4.2z M24,39.8c-8.7,0-15.8-7.1-15.8-15.8S15.3,8.2,24,8.2s15.8,7.1,15.8,15.8S32.7,39.8,24,39.8z", fill: "currentColor" }), h('polygon', { points: "22.2,16.4 22.2,22.2 16.4,22.2 16.4,25.8 22.2,25.8 22.2,31.6 25.8,31.6 25.8,25.8 31.6,31.6 31.6,22.2 25.8,22.2 25.8,16.4 ", fill: "currentColor" })]);
const TMDbIcon = () => h('svg', { xmlns: "http://www.w.org/2000/svg", viewBox: "0 0 512 512", width: "18", height: "18" }, [ h('path', { d: "M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512zM133.2 176.6a22.4 22.4 0 1 1 0-44.8 22.4 22.4 0 1 1 0 44.8zm63.3-22.4a22.4 22.4 0 1 1 44.8 0 22.4 22.4 0 1 1 -44.8 0zm74.8 108.2c-27.5-3.3-50.2-26-53.5-53.5a8 8 0 0 1 16-.6c2.3 19.3 18.8 34 38.1 31.7a8 8 0 0 1 7.4 8c-2.3.3-4.5.4-6.8.4zm-74.8-108.2a22.4 22.4 0 1 1 44.8 0 22.4 22.4 0 1 1 -44.8 0zm149.7 22.4a22.4 22.4 0 1 1 0-44.8 22.4 22.4 0 1 1 0 44.8zM133.2 262.6a22.4 22.4 0 1 1 0-44.8 22.4 22.4 0 1 1 0 44.8zm63.3-22.4a22.4 22.4 0 1 1 44.8 0 22.4 22.4 0 1 1 -44.8 0zm74.8 108.2c-27.5-3.3-50.2-26-53.5-53.5a8 8 0 0 1 16-.6c2.3 19.3 18.8 34 38.1 31.7a8 8 0 0 1 7.4 8c-2.3.3-4.5.4-6.8.4zm-74.8-108.2a22.4 22.4 0 1 1 44.8 0 22.4 22.4 0 1 1 -44.8 0zm149.7 22.4a22.4 22.4 0 1 1 0-44.8 22.4 22.4 0 1 1 0 44.8z", fill: "#01b4e4" })]);

const { configModel } = useConfig();
const message = useMessage();
const props = defineProps({ taskStatus: { type: Object, required: true } });

const allItems = ref([]); 
const displayedItems = ref([]); 
const filter = ref('all');
const isLoading = ref(true);
const error = ref(null);
const showSettingsModal = ref(false);
const subscribing = ref({});
const loaderTrigger = ref(null); 
const PAGE_SIZE = 24; 

const isTaskRunning = (taskName) => props.taskStatus.is_running && props.taskStatus.current_action.includes(taskName);

const filteredItems = computed(() => {
  if (filter.value === 'needed') {
    return allItems.value.filter(item => item.status === 'needed');
  }
  return allItems.value;
});

const getStatusInfo = (status) => {
  switch (status) {
    case 'needed': return { text: '需洗版', type: 'warning' };
    case 'subscribed': return { text: '已订阅', type: 'info' };
    case 'ok': default: return { text: '质量达标', type: 'success' };
  }
};

const fetchData = async () => {
  isLoading.value = true;
  error.value = null;
  try {
    const response = await axios.get('/api/resubscribe/library_status');
    allItems.value = response.data;
  } catch (err) {
    error.value = err.response?.data?.error || '获取洗版状态失败。';
  } finally {
    isLoading.value = false;
  }
};

const loadMore = () => {
  if (isLoading.value || displayedItems.value.length >= filteredItems.value.length) {
    return;
  }
  const currentLength = displayedItems.value.length;
  const nextItems = filteredItems.value.slice(currentLength, currentLength + PAGE_SIZE);
  displayedItems.value.push(...nextItems);
};

// ★★★ 核心修复：在这里解决“赛跑”问题 ★★★
let observer = null;
const setupObserver = () => {
  // 在重新设置前，先断开旧的连接，确保安全
  if (observer) {
    observer.disconnect();
  }
  
  // 等待DOM更新完成后再执行
  nextTick(() => {
    if (loaderTrigger.value) {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting) {
            loadMore();
          }
        },
        { rootMargin: '200px' }
      );
      observer.observe(loaderTrigger.value);
    }
  });
};

watch(filteredItems, (newFilteredItems) => {
  displayedItems.value = newFilteredItems.slice(0, PAGE_SIZE);
  // 当过滤后的列表变化时（包括初始加载），重新设置观察者
  setupObserver();
});

onMounted(fetchData);

onUnmounted(() => {
  if (observer) {
    observer.disconnect();
  }
});

// ... (其他函数 triggerRefreshStatus, triggerResubscribeAll, resubscribeItem, getPosterUrl, openInEmby, watch taskStatus 保持不变) ...
const triggerRefreshStatus = async () => { try { await axios.post('/api/resubscribe/refresh_status'); message.success('刷新任务已提交，请稍后查看任务状态。'); } catch (err) { message.error(err.response?.data?.error || '提交刷新任务失败。'); }};
const triggerResubscribeAll = async () => { try { await axios.post('/api/resubscribe/resubscribe_all'); message.success('一键洗版任务已提交，请稍后查看任务状态。'); } catch (err) { message.error(err.response?.data?.error || '提交一键洗版任务失败。'); }};
const resubscribeItem = async (item) => { subscribing.value[item.item_id] = true; try { const response = await axios.post('/api/resubscribe/resubscribe_item', { item_id: item.item_id, item_name: item.item_name, tmdb_id: item.tmdb_id, item_type: item.item_type, }); message.success(response.data.message); const itemInList = allItems.value.find(i => i.item_id === item.item_id); if (itemInList) { itemInList.status = 'subscribed'; } } catch (err) { message.error(err.response?.data?.error || '洗版订阅失败。'); } finally { subscribing.value[item.item_id] = false; }};
const getPosterUrl = (itemId) => `/image_proxy/Items/${itemId}/Images/Primary?maxHeight=480&tag=1`;
const openInEmby = (itemId) => { const embyServerUrl = configModel.value?.emby_server_url; const serverId = configModel.value?.emby_server_id; if (!embyServerUrl || !itemId) { message.error('Emby服务器地址未配置，无法跳转。'); return; } const baseUrl = embyServerUrl.endsWith('/') ? embyServerUrl.slice(0, -1) : embyServerUrl; let finalUrl = `${baseUrl}/web/index.html#!/item?id=${itemId}`; if (serverId) { finalUrl += `&serverId=${serverId}`; } window.open(finalUrl, '_blank'); };
watch(() => props.taskStatus.is_running, (isRunning, wasRunning) => { if (wasRunning && !isRunning) { const relevantActions = [ '刷新媒体洗版状态', '全库媒体洗版', ]; if (relevantActions.some(action => props.taskStatus.current_action.includes(action))) { message.info('相关后台任务已结束，正在刷新海报墙...'); fetchData(); } } });

</script>

<style scoped>
/* ... 样式部分保持不变 ... */
.watchlist-page { padding: 0 10px; }
.center-container { display: flex; justify-content: center; align-items: center; height: calc(100vh - 200px); }
.series-card { position: relative; }
.card-checkbox { position: absolute; top: 8px; left: 8px; z-index: 10; background-color: rgba(255, 255, 255, 0.7); border-radius: 50%; padding: 4px; --n-color-checked: var(--n-color-primary-hover); --n-border-radius: 50%; opacity: 0; visibility: hidden; transition: opacity 0.2s ease-in-out, visibility 0.2s ease-in-out; }
.series-card:hover .card-checkbox, .card-checkbox.n-checkbox--checked { opacity: 1; visibility: visible; }
.card-poster-container { flex-shrink: 0; width: 160px; height: 240px; overflow: hidden; }
.card-poster { width: 100%; height: 100%; }
.poster-placeholder { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; background-color: var(--n-action-color); }
.card-content-container { flex-grow: 1; display: flex; flex-direction: column; padding: 12px 8px 12px 0; min-width: 0; }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-shrink: 0; }
.card-title { font-weight: 600; font-size: 1.1em; line-height: 1.3; }
.card-status-area { flex-grow: 1; padding-top: 8px; }
.last-checked-text { display: block; font-size: 0.8em; margin-top: 6px; }
.next-episode-text { display: flex; align-items: center; gap: 4px; font-size: 0.8em; }
.card-actions { border-top: 1px solid var(--n-border-color); padding-top: 8px; margin-top: 8px; display: flex; justify-content: space-around; align-items: center; flex-shrink: 0; }
.loader-trigger { height: 50px; display: flex; justify-content: center; align-items: center; }
.series-card.dashboard-card > :deep(.n-card__content) { flex-direction: row !important; justify-content: flex-start !important; padding: 12px !important; gap: 12px !important; }
</style>