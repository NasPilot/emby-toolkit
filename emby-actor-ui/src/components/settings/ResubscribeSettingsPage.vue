<!-- src/components/settings/ResubscribeSettingsPage.vue (多规则改造最终版) -->
<template>
  <n-spin :show="loading">
    <n-space vertical :size="24">
      <n-card :bordered="false">
        <template #header>
          <span style="font-size: 1.2em; font-weight: bold;">媒体洗版规则</span>
        </template>
        <template #header-extra>
          <n-button type="primary" @click="openRuleModal()">
            <template #icon><n-icon :component="AddIcon" /></template>
            新增规则
          </n-button>
        </template>
        <p style="margin-top: 0; color: #888;">
          规则将按列表顺序（从上到下）进行匹配，媒体项会应用匹配到的第一个规则。拖拽规则可以调整优先级。
        </p>
      </n-card>

      <!-- 规则列表 -->
      <draggable
        v-model="rules"
        item-key="id"
        handle=".drag-handle"
        @end="onDragEnd"
        class="rules-list"
      >
        <template #item="{ element: rule }">
          <n-card class="rule-card" :key="rule.id">
            <div class="rule-content">
              <n-icon class="drag-handle" :component="DragHandleIcon" size="20" />
              <div class="rule-details">
                <span class="rule-name">{{ rule.name }}</span>
                <n-tag :type="getLibraryTagType(rule.target_library_ids)" size="small">
                  {{ getLibraryCountText(rule.target_library_ids) }}
                </n-tag>
              </div>
              <n-space class="rule-actions">
                <n-switch v-model:value="rule.enabled" @update:value="toggleRuleStatus(rule)" />
                <n-button text @click="openRuleModal(rule)">
                  <template #icon><n-icon :component="EditIcon" /></template>
                </n-button>
                <n-popconfirm @positive-click="deleteRule(rule.id)">
                  <template #trigger>
                    <n-button text type="error">
                      <template #icon><n-icon :component="DeleteIcon" /></template>
                    </n-button>
                  </template>
                  确定要删除规则 “{{ rule.name }}” 吗？
                </n-popconfirm>
              </n-space>
            </div>
          </n-card>
        </template>
      </draggable>
      <n-empty v-if="rules.length === 0" description="还没有任何规则，快新增一个吧！" />

      <!-- 规则编辑/新增弹窗 -->
      <n-modal v-model:show="showModal" preset="card" style="width: 600px;" :title="modalTitle">
        <n-form ref="formRef" :model="currentRule" :rules="formRules">
          <n-form-item path="name" label="规则名称">
            <n-input v-model:value="currentRule.name" placeholder="例如：4K Remux 收藏规则" />
          </n-form-item>
          <n-form-item path="target_library_ids" label="应用到以下媒体库">
            <n-select
              v-model:value="currentRule.target_library_ids"
              multiple
              filterable
              :options="libraryOptions"
              placeholder="选择一个或多个媒体库"
            />
          </n-form-item>
          <n-form-item>
            <template #label>
              <n-space align="center">
                <span>洗版成功后删除Emby中的媒体项</span>
                <n-tooltip trigger="hover" v-if="!isEmbyAdminConfigured">
                  <template #trigger>
                    <n-icon :component="AlertIcon" style="color: var(--n-warning-color);" />
                  </template>
                  请先在 设置 -> Emby & 虚拟库 标签页中，配置“管理员登录凭证”。
                </n-tooltip>
              </n-space>
            </template>
            <n-switch 
              v-model:value="currentRule.delete_after_resubscribe"
              :disabled="!isEmbyAdminConfigured"
              @update:value="handleDeleteSwitchChange"
            />
          </n-form-item>
          
          <n-divider />

          <!-- 洗版条件 -->
          <n-collapse>
            <n-collapse-item title="按分辨率洗版">
              <template #header-extra>
                <n-switch v-model:value="currentRule.resubscribe_resolution_enabled" @click.stop />
              </template>
              <n-form-item label="洗版分辨率阈值 (宽度)" label-placement="left">
                <n-select
                  v-model:value="currentRule.resubscribe_resolution_threshold"
                  :options="resolutionOptions"
                  :disabled="!currentRule.resubscribe_resolution_enabled"
                />
              </n-form-item>
            </n-collapse-item>
            
            <n-collapse-item title="按质量洗版">
               <template #header-extra>
                <n-switch v-model:value="currentRule.resubscribe_quality_enabled" @click.stop />
              </template>
              <n-form-item label="当文件名【不包含】以下任一关键词时洗版" label-placement="top">
                <n-select
                  v-model:value="currentRule.resubscribe_quality_include"
                  multiple tag filterable placeholder="可选择或自由输入"
                  :options="qualityOptions"
                  :disabled="!currentRule.resubscribe_quality_enabled"
                />
              </n-form-item>
            </n-collapse-item>

            <n-collapse-item title="按特效洗版">
               <template #header-extra>
                <n-switch v-model:value="currentRule.resubscribe_effect_enabled" @click.stop />
              </template>
              <n-form-item label="当文件名【不包含】以下任一关键词时洗版" label-placement="top">
                <n-select
                  v-model:value="currentRule.resubscribe_effect_include"
                  multiple tag filterable placeholder="可选择或自由输入"
                  :options="effectOptions"
                  :disabled="!currentRule.resubscribe_effect_enabled"
                />
              </n-form-item>
            </n-collapse-item>

            <n-collapse-item title="按音轨洗版">
               <template #header-extra>
                <n-switch v-model:value="currentRule.resubscribe_audio_enabled" @click.stop />
              </template>
              <n-form-item label="当缺少以下音轨时洗版 (3字母代码)" label-placement="top">
                <n-select
                  v-model:value="currentRule.resubscribe_audio_missing_languages"
                  multiple tag
                  :options="languageOptions"
                  :disabled="!currentRule.resubscribe_audio_enabled"
                />
              </n-form-item>
            </n-collapse-item>

            <n-collapse-item title="按字幕洗版">
               <template #header-extra>
                <n-switch v-model:value="currentRule.resubscribe_subtitle_enabled" @click.stop />
              </template>
              <n-form-item label="当缺少以下字幕时洗版 (3字母代码)" label-placement="top">
                <n-select
                  v-model:value="currentRule.resubscribe_subtitle_missing_languages"
                  multiple tag
                  :options="subtitleLanguageOptions"
                  :disabled="!currentRule.resubscribe_subtitle_enabled"
                />
              </n-form-item>
            </n-collapse-item>
          </n-collapse>
        </n-form>
        <template #footer>
          <n-button @click="showModal = false">取消</n-button>
          <n-button type="primary" @click="saveRule" :loading="saving">保存</n-button>
        </template>
      </n-modal>

    </n-space>
  </n-spin>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';
import { 
  NCard, NSpace, NSwitch, NButton, useMessage, NSpin, NIcon, NPopconfirm, NModal, NForm, 
  NFormItem, NInput, NSelect, NDivider, NCollapse, NCollapseItem, NTag, NEmpty
} from 'naive-ui';
import draggable from 'vuedraggable';
import { 
  Add as AddIcon, Pencil as EditIcon, Trash as DeleteIcon, Move as DragHandleIcon, AlertCircleOutline as AlertIcon, 
} from '@vicons/ionicons5';

const message = useMessage();
const embyAdminUser = ref('');
const embyAdminPass = ref('');

// 计算属性，实时判断管理员账密是否已配置
const isEmbyAdminConfigured = computed(() => {
  return embyAdminUser.value && embyAdminPass.value;
});
const loading = ref(true);
const saving = ref(false);
const showModal = ref(false);

const rules = ref([]);
const currentRule = ref({});
const formRef = ref(null);
const libraryOptions = ref([]);

const isEditing = computed(() => currentRule.value && currentRule.value.id);
const modalTitle = computed(() => isEditing.value ? '编辑规则' : '新增规则');

const formRules = {
  name: { required: true, message: '请输入规则名称', trigger: 'blur' },
  target_library_ids: { type: 'array', required: true, message: '请至少选择一个媒体库', trigger: 'change' },
};

// --- Options for Selects ---
const resolutionOptions = ref([
  { label: '低于 4K (3840px)', value: 3840 },
  { label: '低于 1080p (1920px)', value: 1920 },
  { label: '低于 720p (1280px)', value: 1280 },
]);
const qualityOptions = ref([
  { label: 'Remux', value: 'remux' }, { label: 'BluRay / 蓝光', value: 'bluray' },
  { label: 'WEB-DL', value: 'web-dl' }, { label: 'UHD', value: 'uhd' },
  { label: 'BDRip', value: 'bdrip' }, { label: 'HDTV', value: 'hdtv' },
]);
const effectOptions = ref([
  { label: 'HDR', value: 'hdr' }, { label: 'Dolby Vision / DoVi', value: 'dovi' },
  { label: 'HDR10+', value: 'hdr10+' }, { label: 'HLG', value: 'hlg' },
]);
const languageOptions = ref([
    { label: '国语 (chi)', value: 'chi' }, { label: '粤语 (yue)', value: 'yue' },
    { label: '英语 (eng)', value: 'eng' }, { label: '日语 (jpn)', value: 'jpn' },
]);
const subtitleLanguageOptions = ref([
    { label: '中字 (chi)', value: 'chi' }, { label: '英字 (eng)', value: 'eng' },
]);

// --- API Calls ---
const loadData = async () => {
  loading.value = true;
  try {
    // ▼▼▼ 把 Promise.all 改成这样，增加第三个请求 ▼▼▼
    const [rulesRes, libsRes, configRes] = await Promise.all([
      axios.get('/api/resubscribe/rules'),
      axios.get('/api/resubscribe/libraries'),
      axios.get('/api/config') // ★ 新增：获取完整配置
    ]);
    
    rules.value = rulesRes.data;
    libraryOptions.value = libsRes.data;

    // ★ 新增：从完整配置中提取我们需要的管理员账密
    embyAdminUser.value = configRes.data.emby_admin_user;
    embyAdminPass.value = configRes.data.emby_admin_pass;

  } catch (error) {
    message.error('加载数据失败，请检查网络或后端日志。');
  } finally {
    loading.value = false;
  }
};

const handleDeleteSwitchChange = (value) => {
  if (value && !isEmbyAdminConfigured.value) {
    // 如果用户尝试打开开关，但配置不完整
    message.warning('请先在 设置 -> Emby & 虚拟库 标签页中，配置“管理员登录凭证”，否则删除功能无法生效。');
    // 阻止开关被打开
    nextTick(() => {
      currentRule.value.delete_after_resubscribe = false;
    });
  }
};

const openRuleModal = async (rule = null) => {
  // ▼▼▼ 在函数开头加入加载逻辑 ▼▼▼
  try {
    // 显示加载状态
    saving.value = true; 
    const libsRes = await axios.get('/api/resubscribe/libraries');
    libraryOptions.value = libsRes.data;
  } catch (error) {
    message.error('获取媒体库列表失败！');
    saving.value = false;
    return; // 获取失败则不打开弹窗
  } finally {
    saving.value = false;
  }
  if (rule) {
    // Deep copy for editing to avoid reactive changes before saving
    currentRule.value = JSON.parse(JSON.stringify(rule));
  } else {
    // Default new rule structure
    currentRule.value = {
      name: '',
      enabled: true,
      target_library_ids: [],
      delete_after_resubscribe: false,
      resubscribe_resolution_enabled: false,
      resubscribe_resolution_threshold: 1920,
      resubscribe_audio_enabled: false,
      resubscribe_audio_missing_languages: [],
      resubscribe_subtitle_enabled: false,
      resubscribe_subtitle_missing_languages: [],
      resubscribe_quality_enabled: false,
      resubscribe_quality_include: [],
      resubscribe_effect_enabled: false,
      resubscribe_effect_include: [],
    };
  }
  showModal.value = true;
};

const saveRule = async () => {
  formRef.value?.validate(async (errors) => {
    if (!errors) {
      saving.value = true;
      try {
        if (isEditing.value) {
          await axios.put(`/api/resubscribe/rules/${currentRule.value.id}`, currentRule.value);
          message.success('规则已更新！');
        } else {
          await axios.post('/api/resubscribe/rules', currentRule.value);
          message.success('规则已创建！');
        }
        showModal.value = false;
        loadData(); // Reload all rules
      } catch (error) {
        message.error(error.response?.data?.error || '保存失败，请检查后端日志。');
      } finally {
        saving.value = false;
      }
    }
  });
};

const deleteRule = async (ruleId) => {
  try {
    await axios.delete(`/api/resubscribe/rules/${ruleId}`);
    message.success('规则已删除！');
    loadData();
  } catch (error) {
    message.error('删除失败，请检查后端日志。');
  }
};

const toggleRuleStatus = async (rule) => {
  try {
    await axios.put(`/api/resubscribe/rules/${rule.id}`, { enabled: rule.enabled });
    message.success(`规则 “${rule.name}” 已${rule.enabled ? '启用' : '禁用'}`);
  } catch (error) {
    message.error('状态更新失败');
    rule.enabled = !rule.enabled; // Revert on failure
  }
};

const onDragEnd = async () => {
  const orderedIds = rules.value.map(r => r.id);
  try {
    await axios.post('/api/resubscribe/rules/order', orderedIds);
    message.success('规则优先级已更新！');
  } catch (error) {
    message.error('顺序保存失败，将刷新列表。');
    loadData(); // Revert to server order on failure
  }
};

// --- UI Helpers ---
const getLibraryCountText = (libs) => {
  if (!libs || libs.length === 0) return '未指定媒体库';
  return `应用于 ${libs.length} 个媒体库`;
};
const getLibraryTagType = (libs) => {
  return (!libs || libs.length === 0) ? 'error' : 'success';
};

onMounted(loadData);
</script>

<style scoped>
.rules-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rule-card {
  cursor: pointer;
}
.rule-content {
  display: flex;
  align-items: center;
  gap: 16px;
}
.drag-handle {
  cursor: grab;
  color: #888;
}
.rule-details {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
}
.rule-name {
  font-weight: bold;
}
.rule-actions {
  margin-left: auto;
}
</style>