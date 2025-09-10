<template>
  <n-modal
    :show="props.show"
    @update:show="val => emit('update:show', val)"
    preset="card"
    style="width: 95%; max-width: 1200px;"
    :title="subscriptionData ? `订阅详情 - ${subscriptionData.actor_name}` : '加载中...'"
    :bordered="false"
    size="huge"
  >
    <div v-if="loading" style="text-align: center; padding: 50px 0;"><n-spin size="large" /></div>
    <div v-else-if="error" style="text-align: center; padding: 50px 0;"><n-alert title="加载失败" type="error">{{ error }}</n-alert></div>
    <div v-else-if="subscriptionData">
      <n-tabs type="line" animated default-value="tracking">
        <n-tab-pane name="tracking" tab="追踪列表">
          <n-data-table
            :columns="columns"
            :data="subscriptionData.tracked_media"
            :pagination="{ pageSize: 10 }"
            :bordered="false"
            size="small"
          />
        </n-tab-pane>
        <n-tab-pane name="config" tab="订阅配置">
          <div style="max-width: 600px; margin: 0 auto; padding: 20px 0;">
            <p style="margin-bottom: 20px;">在这里可以修改订阅配置，保存后将对未来的扫描生效。</p>
            <!-- ★★★ 核心修复 1：使用正确的 v-model 绑定 ★★★ -->
            <subscription-config-form v-model="editableConfig" />
            <n-space justify="end" style="margin-top: 20px;">
              <n-button @click="resetConfig">重置更改</n-button>
              <n-button type="primary" @click="saveConfig">保存配置</n-button>
            </n-space>
          </div>
        </n-tab-pane>
      </n-tabs>
    </div>
    <template #footer>
      <n-space justify="space-between">
        <n-space>
        <n-popconfirm @positive-click="handleDelete">
          <template #trigger>
            <n-button type="error" ghost>删除此订阅</n-button>
          </template>
          确定要删除对该演员的订阅吗？所有追踪记录将一并清除。
        </n-popconfirm>
        <n-button
            v-if="subscriptionData"
            :type="subscriptionData.status === 'active' ? 'warning' : 'success'"
            ghost
            @click="handleToggleStatus"
        >
            {{ subscriptionData.status === 'active' ? '暂停订阅' : '恢复订阅' }}
        </n-button>
        </n-space>
        <n-button type="primary" @click="handleRefresh">手动刷新</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup>
import { ref, watch, h } from 'vue';
import { NModal, NSpin, NAlert, NTabs, NTabPane, NDataTable, NTag, NButton, NSpace, NPopconfirm, useMessage } from 'naive-ui';
import axios from 'axios';
import SubscriptionConfigForm from './SubscriptionConfigForm.vue';

const props = defineProps({
  show: Boolean,
  subscriptionId: Number,
});
const emit = defineEmits(['update:show', 'subscription-updated', 'subscription-deleted']);

const message = useMessage();
const loading = ref(false);
const error = ref(null);
const subscriptionData = ref(null);
const editableConfig = ref({});

// 定义数据表的列
const columns = [
  {
    title: '海报',
    key: 'poster_path',
    render(row) {
      const url = row.poster_path ? `https://image.tmdb.org/t/p/w92${row.poster_path}` : 'https://via.placeholder.com/92x138.png?text=N/A';
      return h('img', { src: url, style: 'width: 45px; height: 67px; object-fit: cover; border-radius: 3px;' });
    }
  },
  { title: '标题', key: 'title', ellipsis: { tooltip: true } },
  { 
    title: '类型', 
    key: 'media_type', 
    width: 80,
    render(row) {
      const typeMap = {
        'Series': '电视剧',
        'Movie': '电影'
      };
      return typeMap[row.media_type] || row.media_type;
    }
  },
  {
  title: '发行日期',
  key: 'release_date',
  width: 120,
  render(row) {
  if (!row.release_date) return '';
  const date = new Date(row.release_date);
  // 使用 toLocaleDateString 带 zh-CN 区域，不带任何额外格式化，直接返回 yyyy/MM/dd
  return date.toLocaleDateString('zh-CN');
}
},
  {
    title: '状态',
    key: 'status',
    render(row) {
      const statusMap = {
        'IN_LIBRARY': { type: 'success', text: '已入库' },
        'SUBSCRIBED': { type: 'info', text: '已订阅' },
        'PENDING_RELEASE': { type: 'default', text: '待发行' },
        'MISSING': { type: 'error', text: '缺失' },
      };
      const info = statusMap[row.status] || { type: 'warning', text: '未知' };
      return h(NTag, { type: info.type, size: 'small', round: true }, { default: () => info.text });
    }
  }
];

const fetchDetails = async (id) => {
  if (!id) return;
  loading.value = true;
  error.value = null;
  subscriptionData.value = null;
  try {
    const response = await axios.get(`/api/actor-subscriptions/${id}`);
    subscriptionData.value = response.data;
    resetConfig();
  } catch (err) {
    error.value = err.response?.data?.error || '加载订阅详情失败。';
  } finally {
    loading.value = false;
  }
};

const resetConfig = () => {
  // 确保我们有数据和嵌套的 config 对象
  if (!subscriptionData.value || !subscriptionData.value.config) return;

  // 直接引用加载到的 config 对象，让代码更清晰
  const config = subscriptionData.value.config;

  // 使用加载到的数据填充表单的 v-model
  editableConfig.value = {
    start_year: config.start_year || 1900,
    media_types: config.media_types || ['Movie', 'TV'],
    genres_include_json: config.genres_include_json || [],
    genres_exclude_json: config.genres_exclude_json || [],
    min_rating: config.min_rating || 6.0,
  };
};

const saveConfig = async () => {
  if (!props.subscriptionId) return;
  try {
    const payload = {
      config: editableConfig.value
    };
    await axios.put(`/api/actor-subscriptions/${props.subscriptionId}`, payload);
    
    message.success('配置已成功保存！');
    emit('subscription-updated');
    fetchDetails(props.subscriptionId);
  } catch (err) {
    message.error(err.response?.data?.error || '保存配置失败。');
  }
};

const handleDelete = async () => {
  if (!props.subscriptionId) return;
  try {
    await axios.delete(`/api/actor-subscriptions/${props.subscriptionId}`);
    message.success('订阅已成功删除！');
    emit('subscription-deleted');
    emit('update:show', false);
  } catch (err) {
    message.error(err.response?.data?.error || '删除订阅失败。');
  }
};

const handleRefresh = async () => {
  if (!props.subscriptionId) return;
  try {
    await axios.post(`/api/actor-subscriptions/${props.subscriptionId}/refresh`);
    message.success('手动刷新任务已提交到后台！请稍后查看任务状态。');
    emit('update:show', false);
  } catch (err) {
    message.error(err.response?.data?.error || '启动刷新任务失败。');
  }
};
const handleToggleStatus = async () => {
  if (!props.subscriptionId || !subscriptionData.value || !subscriptionData.value.config) return;

  const newStatus = subscriptionData.value.status === 'active' ? 'paused' : 'active';
  const actionText = newStatus === 'paused' ? '暂停' : '恢复';

  try {
    // 使用正确的、嵌套的 config 对象作为数据源
    const currentConfig = subscriptionData.value.config;

    const payload = {
      status: newStatus,
      config: {
        start_year: currentConfig.start_year,
        // 为符合后端 API 要求，将数组转回字符串
        media_types: currentConfig.media_types.join(','),
        genres_include_json: JSON.stringify(currentConfig.genres_include_json),
        genres_exclude_json: JSON.stringify(currentConfig.genres_exclude_json),
        min_rating: currentConfig.min_rating
      }
    };

    await axios.put(`/api/actor-subscriptions/${props.subscriptionId}`, payload);

    message.success(`订阅已成功${actionText}！`);
    emit('subscription-updated');
    await fetchDetails(props.subscriptionId);

  } catch (err) {
    message.error(err.response?.data?.error || `${actionText}订阅失败。`);
  }
};

watch(() => props.subscriptionId, (newId) => {
  if (newId && props.show) {
    fetchDetails(newId);
  }
});

watch(() => props.show, (newVal) => {
  if (newVal && props.subscriptionId) {
    fetchDetails(props.subscriptionId);
  }
});
</script>