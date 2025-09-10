<!-- src/components/settings/SchedulerSettingsPage.vue -->
<template>
  <n-layout content-style="padding: 24px;">
    <!-- 加载状态 -->
    <div v-if="isLoading" class="center-container">
      <n-spin size="large" />
    </div>
    
    <n-space v-else-if="configModel" vertical :size="24" style="margin-top: 15px;">
      
      <!-- 卡片 1: 自动化维护任务链 (V2 - 两列布局) -->
      <n-card :bordered="false" class="dashboard-card">
        <template #header>
          <span class="card-title">自动化任务链</span>
        </template>
        
        <!-- --- 【【【 使用 Grid 组件实现两列布局 】】】 --- -->
        <n-grid cols="1 l:2" :x-gap="24" :y-gap="16" responsive="screen">
          
          <!-- 左侧列：配置区域 -->
          <n-gi>
            <n-space vertical>
              <n-space align="center" justify="space-between">
                <n-text strong>启用自动化任务链</n-text>
                <n-switch v-model:value="configModel.task_chain_enabled" />
              </n-space>
              <n-form :model="configModel" label-placement="left" label-width="auto" class="mt-3" :show-feedback="false">
                <n-form-item label="定时执行 (CRON)">
                  <n-input v-model:value="configModel.task_chain_cron" :disabled="!configModel.task_chain_enabled" placeholder="例如: 0 2 * * *" />
                </n-form-item>
                <n-form-item label="任务序列">
                  <n-button-group>
                    <n-button type="default" @click="showChainConfigModal = true" :disabled="!configModel.task_chain_enabled">
                      <template #icon><n-icon :component="Settings24Regular" /></template>
                      配置
                    </n-button>
                    <n-button type="primary" @click="savePageConfig" :loading="savingConfig">
                      <template #icon><n-icon :component="Save24Regular" /></template>
                      保存配置
                    </n-button>
                  </n-button-group>
                </n-form-item>
              </n-form>
            </n-space>
          </n-gi>

          <!-- 右侧列：显示当前执行顺序 -->
          <n-gi>
            <n-text strong>当前执行流程</n-text>
            <div class="flowchart-wrapper">
              <div v-if="enabledTaskChain.length > 0" class="flowchart-container">
                <div v-for="task in enabledTaskChain" :key="task.key" class="flowchart-node">
                  {{ task.name }}
                </div>
              </div>
              <div v-else class="flowchart-container empty">
                <n-text depth="3">暂未配置任何任务...</n-text>
              </div>
            </div>
          </n-gi>


        </n-grid>
        <!-- --- 【【【 Grid 布局结束 】】】 --- -->

        <!-- "工作原理"提示信息，放在 Grid 下方，保持通栏显示 -->
        <n-alert title="任务详情" type="info" style="margin-top: 24px;">
          启用后，系统将只在指定时间执行一个总任务。该任务会严格按照“配置任务链”中设定好的顺序，一个接一个地执行选中的子任务，无需再为每个任务单独设置时间，彻底避免了任务冲突。<br />
          建议顺序：[同步演员映射->同步媒体数据->演员数据补充->中文化角色名],其他任务随意。<br />
          处理模式：快速模式是增量处理，会跳过已处理过的媒体项；深度模式是无视已处理记录全量重新处理一遍。自动化任务链默认采用快速模式，手动立即执行才可以选择深度模式。
        </n-alert>
      </n-card>

      <!-- 卡片 2: 临时任务 -->
      <n-card :bordered="false" class="dashboard-card">
        <template #header>
          <span class="card-title">临时任务</span>
        </template>
        <template #header-extra>
          <n-text depth="3">用于需要立即手动执行的场景</n-text>
        </template>
        <n-grid cols="1 m:2 l:3" :x-gap="24" :y-gap="16" responsive="screen">
          <n-gi v-for="task in availableTasksForManualRun" :key="task.key">
            <div class="temp-task-item">
              <n-text>{{ task.name }}</n-text>
              <n-button size="small" type="primary" ghost @click="triggerTaskNow(task.key)" :loading="isTriggeringTask === task.key" :disabled="isBackgroundTaskRunning">
                <template #icon><n-icon :component="Play24Regular" /></template>
                立即执行
              </n-button>
            </div>
          </n-gi>
        </n-grid>
      </n-card>

      
    </n-space>

    <!-- 任务链配置模态框 (保持不变) -->
    <n-modal
      v-model:show="showChainConfigModal"
      class="custom-card"
      preset="card"
      title="配置任务链执行顺序"
      style="width: 90%; max-width: 600px;"
      :mask-closable="false"
    >
      <n-alert type="info" :show-icon="false" style="margin-bottom: 16px;">
        请勾选需要定时执行的任务，并拖动任务调整它们的执行顺序。
      </n-alert>
      <div class="task-chain-list" ref="draggableContainer">
        <div v-for="task in configuredTaskSequence" :key="task.key" class="task-chain-item" :data-key="task.key">
          <n-icon :component="Drag24Regular" class="drag-handle" />
          <n-checkbox v-model:checked="task.enabled" style="flex-grow: 1;">
            {{ task.name }}
          </n-checkbox>
        </div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showChainConfigModal = false">取消</n-button>
          <n-button type="primary" @click="saveTaskChainConfig">保存</n-button>
        </n-space>
      </template>
    </n-modal>
    <n-modal
      v-model:show="showSyncModeModal"
      preset="dialog"
      title="选择同步模式"
      :mask-closable="false"
    >
      <n-text>您希望如何执行此任务？</n-text>
      <template #action>
        <n-button @click="showSyncModeModal = false">取消</n-button>
        <n-button @click="runTaskFromModal(false)">快速模式（增量）</n-button>
        <n-button type="warning" @click="runTaskFromModal(true)">
          深度模式 (全量)
        </n-button>
      </template>
    </n-modal>
  </n-layout>
</template>

<script setup>
import { ref, onMounted, watch, nextTick, computed } from 'vue';
import {
  NForm, NFormItem, NInput, NCheckbox, NGrid, NGi, NAlert,
  NButton, NCard, NSpace, NSwitch, NIcon, NText,
  useMessage, NLayout, NSpin, NModal
} from 'naive-ui';
import { Play24Regular, Settings24Regular, Drag24Regular, Save24Regular } from '@vicons/fluent';
import { useConfig } from '../../composables/useConfig.js';
import { useTaskStatus } from '../../composables/useTaskStatus.js';
import axios from 'axios';
import Sortable from 'sortablejs';

const message = useMessage();

// --- Composable Hooks ---
const {
    configModel,
    loadingConfig: isLoading,
    handleSaveConfig,
    savingConfig,
    configError
} = useConfig();

const { isBackgroundTaskRunning } = useTaskStatus();

// --- State ---
const showChainConfigModal = ref(false);
const availableTasksForChain = ref([]); // 从后端获取的所有可用于任务链的任务
const availableTasksForManualRun = ref([]); // 从后端获取的所有可用于手动运行的任务
const configuredTaskSequence = ref([]); // 用于模态框中配置的任务列表
const isTriggeringTask = ref(null);
const draggableContainer = ref(null);
let sortableInstance = null;
const showSyncModeModal = ref(false); // 新的、通用的模态框显示状态
const taskToRunInModal = ref(null); // 用于存储当前点击的任务ID
// ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
// --- 【【【 核心修改：使用 computed 属性来动态计算已启用的任务列表 】】】 ---
const enabledTaskChain = computed(() => {
  if (!configuredTaskSequence.value) return [];
  return configuredTaskSequence.value.filter(t => t.enabled);
});
// ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

// --- API Calls ---
const fetchAvailableTasks = async () => {
  try {
    // 获取用于任务链的、已筛选的任务
    const chainResponse = await axios.get('/api/tasks/available?context=chain');
    availableTasksForChain.value = chainResponse.data;

    // 获取所有任务，用于“临时任务”区域的手动执行
    const allResponse = await axios.get('/api/tasks/available?context=all');
    availableTasksForManualRun.value = allResponse.data;

  } catch (error) {
    message.error('获取可用任务列表失败！');
  }
};

const runTaskFromModal = async (isDeepMode) => {
  showSyncModeModal.value = false;
  const taskIdentifier = taskToRunInModal.value;
  if (!taskIdentifier) return;

  isTriggeringTask.value = taskIdentifier;

  try {
    const payload = {
      task_name: taskIdentifier,
    };
    // ★★★ 核心修改：为所有需要模式选择的任务动态添加参数 ★★★
    if (taskIdentifier === 'full-scan') {
      payload.force_reprocess = isDeepMode;
    } 
    else if (
      taskIdentifier === 'populate-metadata' || 
      taskIdentifier === 'sync-images-map' ||
      taskIdentifier === 'enrich-aliases' 
    ) {
      payload.force_full_update = isDeepMode;
    }

    const response = await axios.post('/api/tasks/run', payload);
    message.success(response.data.message || '任务已成功提交！');
  } catch (error) {
    const errorMessage = error.response?.data?.error || '请求后端接口失败。';
    message.error(errorMessage);
  } finally {
    isTriggeringTask.value = null;
    taskToRunInModal.value = null;
  }
};

const triggerTaskNow = async (taskIdentifier) => {
  if (isBackgroundTaskRunning.value) {
    message.warning('已有后台任务正在运行，请稍后再试。');
    return;
  }

  // 如果是“全量处理和同步媒体数据”，则显示模态框，而不是直接执行
  if (['full-scan', 'populate-metadata', 'sync-images-map', 'enrich-aliases'].includes(taskIdentifier)) {
    taskToRunInModal.value = taskIdentifier; 
    showSyncModeModal.value = true;
    return; 
  }

  // --- 对于所有其他普通任务，走原来的逻辑 ---
  isTriggeringTask.value = taskIdentifier;
  try {
    const response = await axios.post('/api/tasks/run', {
      task_name: taskIdentifier
    });
    message.success(response.data.message || `任务已成功提交！`);
  } catch (error) {
    const errorMessage = error.response?.data?.error || '请求后端接口失败。';
    message.error(errorMessage);
  } finally {
    isTriggeringTask.value = null;
  }
};

const runFullScan = async (isForced) => {
  showFullScanModal.value = false; // 首先关闭模态框
  isTriggeringTask.value = 'full-scan'; // 设置加载状态

  try {
    const response = await axios.post('/api/tasks/run', {
      task_name: 'full-scan',
      force_reprocess: isForced // ★★★ 将用户的选择作为参数传递给后端
    });
    message.success(response.data.message || '全量处理任务已成功提交！');
  } catch (error) {
    const errorMessage = error.response?.data?.error || '请求后端接口失败。';
    message.error(errorMessage);
  } finally {
    isTriggeringTask.value = null; // 清除加载状态
  }
};

// --- Logic ---
const savePageConfig = async () => {
  if (configModel.value) {
    configModel.value.task_chain_sequence = enabledTaskChain.value.map(t => t.key);
  }
  const success = await handleSaveConfig();
  if (success) {
    message.success('配置已成功保存！');
  } else {
    message.error(configError.value || '配置保存失败。');
  }
};

const saveTaskChainConfig = () => {
  showChainConfigModal.value = false;
  message.info('任务链顺序已在页面上更新，请点击“保存配置”按钮以持久化更改。');
};

const initializeTaskSequence = () => {
  if (!configModel.value || !availableTasksForChain.value.length) return;

  const savedSequence = configModel.value.task_chain_sequence || [];
  const savedSequenceSet = new Set(savedSequence);

  const enabledTasks = savedSequence
    .map(key => {
      const task = availableTasksForChain.value.find(t => t.key === key);
      return task ? { ...task, enabled: true } : null;
    })
    .filter(Boolean);

  const disabledTasks = availableTasksForChain.value
    .filter(task => !savedSequenceSet.has(task.key))
    .map(task => ({ ...task, enabled: false }));

  configuredTaskSequence.value = [...enabledTasks, ...disabledTasks];
};

const initializeSortable = () => {
  if (draggableContainer.value) {
    sortableInstance = Sortable.create(draggableContainer.value, {
      animation: 150,
      handle: '.drag-handle',
      onEnd: (evt) => {
        const { oldIndex, newIndex } = evt;
        const item = configuredTaskSequence.value.splice(oldIndex, 1)[0];
        configuredTaskSequence.value.splice(newIndex, 0, item);
      },
    });
  }
};

// --- Lifecycle and Watchers ---
onMounted(() => {
  fetchAvailableTasks();
});

watch(showChainConfigModal, (newValue) => {
  if (newValue) {
    nextTick(() => {
      initializeSortable();
    });
  } else {
    if (sortableInstance) {
      sortableInstance.destroy();
      sortableInstance = null;
    }
  }
});

watch([configModel, availableTasksForChain], ([newConfig, newTasks]) => {
  if (newConfig && newTasks.length > 0) {
    initializeTaskSequence();
  }
}, { immediate: true });
</script>

<style scoped>
.center-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: calc(100vh - 200px);
}
.mt-3 {
  margin-top: 12px;
}
.temp-task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 4px;
}
.task-chain-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.task-chain-item {
  display: flex;
  align-items: center;
  padding: 10px;
  background-color: var(--n-action-color);
  border-radius: 4px;
  border: 1px solid var(--n-border-color);
  transition: background-color 0.3s;
}
.task-chain-item.sortable-ghost {
  background-color: var(--n-color-target-suppl);
}
.drag-handle {
  cursor: grab;
  margin-right: 12px;
  color: var(--n-text-color-disabled);
}
.drag-handle:active {
  cursor: grabbing;
}

/* ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ */
/* --- 【【【 新增：流程图核心样式 】】】 --- */
.flowchart-wrapper {
  margin-top: 12px;
  padding: 16px;
  border-radius: 4px;
  min-height: 100px;
  width: 100%;
}
.flowchart-container {
  display: flex;
  flex-wrap: wrap; /* 允许换行 */
  align-items: center;
  gap: 8px 0; /* 垂直间隙8px，水平间隙0（由连接器控制） */
}
.flowchart-container.empty {
  justify-content: center; /* 空状态时居中显示文字 */
  height: 100%;
}
.flowchart-node {
  background-color: var(--n-color);
  border: 1px solid var(--n-border-color);
  padding: 8px 16px;
  border-radius: 20px; /* 圆角矩形 */
  text-align: center;
  white-space: nowrap;
  position: relative; /* 为连接器定位 */
}
/* 使用 ::after 伪元素创建连接器（箭头） */
.flowchart-node:not(:last-child)::after {
  content: '';
  position: absolute;
  right: -20px; /* 将箭头定位在节点右侧 */
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  /* 使用内联SVG作为箭头，可以继承颜色 */
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='currentColor'%3E%3Cpath d='M16.172 11l-5.364-5.364 1.414-1.414L20 12l-7.778 7.778-1.414-1.414L16.172 13H4v-2z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  opacity: 0.5;
}

/* --- 响应式设计：当屏幕变窄时，变为垂直流程图 --- */
@media (max-width: 1200px) { /* 这个断点值可以根据实际情况调整 */
  .flowchart-container {
    flex-direction: column; /* 垂直排列 */
    align-items: flex-start; /* 左对齐 */
    gap: 0 8px; /* 水平间隙8px，垂直间隙0 */
  }
  .flowchart-node {
    width: fit-content; /* 宽度自适应内容 */
  }
  .flowchart-node:not(:last-child)::after {
    /* 调整箭头位置和方向 */
    right: auto;
    left: 50%;
    top: 100%;
    transform: translateX(-50%);
    /* 切换为向下的箭头SVG */
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='currentColor'%3E%3Cpath d='M13 16.172l5.364-5.364 1.414 1.414L12 20l-7.778-7.778 1.414-1.414L11 16.172V4h2z'/%3E%3C/svg%3E");
  }
}
</style>