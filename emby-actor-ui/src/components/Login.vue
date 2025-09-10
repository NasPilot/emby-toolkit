<template>
  <div class="login-container">
    <n-card title="登录" class="login-card">
      <n-form @submit.prevent="handleLogin">
        <n-form-item-row label="用户名">
          <n-input v-model:value="credentials.username" placeholder="请输入用户名" />
        </n-form-item-row>
        <n-form-item-row label="密码">
          <n-input
            type="password"
            show-password-on="mousedown"
            v-model:value="credentials.password"
            placeholder="请输入密码"
          />
        </n-form-item-row>
        <n-button type="primary" attr-type="submit" block :loading="loading">
          登 录
        </n-button>
      </n-form>
    </n-card>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router'; // ★ 1. 重新导入 useRouter
import { NCard, NForm, NFormItemRow, NInput, NButton, useMessage } from 'naive-ui';
import { useAuthStore } from '../stores/auth';

const router = useRouter(); // ★ 2. 获取 router 实例
const credentials = ref({
  username: '',
  password: '',
});
const loading = ref(false);
const message = useMessage();
const authStore = useAuthStore();

async function handleLogin() {
  if (!credentials.value.username || !credentials.value.password) {
    message.error('请输入用户名和密码');
    return;
  }
  loading.value = true;
  try {
    await authStore.login(credentials.value);
    message.success('登录成功！');
    
    // ★ 3. 登录成功后，明确地告诉路由器跳转到主页 ★
    // 我们跳转到 'DatabaseStats' (数据看板)，这是您现在的默认首页
    router.push({ name: 'DatabaseStats' }); 

  } catch (error) {
    const errorMessage = error.response?.data?.error || error.message || '登录失败，请检查网络或联系管理员';
    message.error(errorMessage);
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  width: 100%;
}
.login-card {
  width: 100%;
  max-width: 400px;
}
</style>