<template>
  <section class="page" data-module="parser">
    <header class="page-head">
      <div>
        <h2>格式解析器管理</h2>
        <p class="page-desc">维护解析配置，围绕解析编号、输入格式、输出格式、字段映射做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记解析配置</button>
        <button class="btn" type="button" @click="exportRows">导出格式解析器清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无格式解析器数据，可先登记解析配置</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条格式解析器记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="detail-panel">
      <header class="detail-head">
        <h3>正文记录与通知溯源（按网页采集规则发布快照解析）</h3>
      </header>
      <form class="filter-bar" @submit.prevent="loadTrace">
        <label class="filter-item">
          <span>通知规则编号</span>
          <input v-model="ruleCode" placeholder="如 CRAW-0004" />
        </label>
        <label class="filter-item">
          <span>使用的解析配置</span>
          <select v-model="selectedParserId">
            <option v-for="p in enabledParsers" :key="String(p.id)" :value="Number(p.id)">
              {{ p['解析编号'] }}（{{ p['输入格式'] }}→{{ p['输出格式'] }}）
            </option>
          </select>
        </label>
        <button class="btn primary" type="button" @click="parseRulePages">解析该规则已抓页面</button>
        <button class="btn" type="submit">查看通知溯源</button>
      </form>
      <p v-if="parseMessage" class="detail-message">{{ parseMessage }}</p>

      <template v-if="notification">
        <div class="closure-banner" :class="{ hit: notification['闭馆时间是否已进入本次通知'] }">
          闭馆时间是否已进入本次通知：{{ notification['闭馆时间是否已进入本次通知'] ? '是' : '否' }}
          <span v-for="(text, i) in notification['闭馆信息']" :key="i" class="closure-text">{{ text }}</span>
        </div>
        <p class="page-desc">
          页面：
          <span v-for="p in notification['页面']" :key="String(p['页面id'])" class="page-chip">
            第{{ p['页码'] }}页 · v{{ p['快照版本'] }} · {{ p['是否已解析'] ? '已解析' : '未解析' }}
          </span>
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th v-for="column in recordColumns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in notification['段落']" :key="String(record['记录编号'])" :class="{ 'closure-row': record['是否闭馆信息'] }">
              <td v-for="column in recordColumns" :key="column">{{ record[column] ?? '—' }}</td>
            </tr>
            <tr v-if="!notification['段落'].length">
              <td :colspan="recordColumns.length" class="empty-state">还没有正文记录，请先解析已抓页面</td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记解析配置</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Notification = {
  规则编号: string
  目标网址: string
  闭馆时间是否已进入本次通知: boolean
  闭馆信息: string[]
  页面: Array<Record<string, string | number | boolean>>
  段落: Array<Record<string, string | number | boolean>>
}

const ENDPOINT = '/api/parser'
const columns = ["解析编号", "输入格式", "输出格式", "字段映射", "类型转换", "空值处理", "异常策略", "解析状态"]
const actions = ["提交配置", "启用解析", "废弃解析"]
const statuses = ["草稿", "已配置", "生效中", "已废弃"]
const stats = [{"label": "解析器总数", "value": 0}, {"label": "生效中解析器", "value": 0}, {"label": "已废弃解析器", "value": 0}]
const recordColumns = ["记录编号", "页码", "快照版本", "正文选择器", "正文文本"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

const ruleCode = ref('CRAW-0004')
const selectedParserId = ref<number>(0)
const parseMessage = ref('')
const notification = ref<Notification | null>(null)

const enabledParsers = computed(() => rows.value.filter((row) => row.status === '生效中'))

function updateStats() {
  const data = rows.value
  stats.length > 0 && (stats[0].value = data.filter((r: Row) => r.status === statuses[1] || r.pending).length)
  stats.length > 1 && (stats[1].value = data.filter((r: Row) => r.status && !r.pending && !r.abnormal).length)
  stats.length > 2 && (stats[2].value = data.filter((r: Row) => r.abnormal).length)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) {
      throw new Error(data.message || '格式解析器动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '格式解析器操作失败'
  }
}

async function findRuleId(): Promise<number> {
  const response = await request(`/api/crawler?keyword=${encodeURIComponent(ruleCode.value)}`)
  const payload = await response.json()
  const match = (payload.items ?? []).find((item: Row) => item['规则编号'] === ruleCode.value)
  if (!match) {
    throw new Error(`采集规则 ${ruleCode.value} 不存在`)
  }
  return Number(match.id)
}

async function parseRulePages() {
  parseMessage.value = ''
  try {
    if (!selectedParserId.value) {
      throw new Error('没有生效中的解析配置，请先启用解析')
    }
    const ruleId = await findRuleId()
    const response = await request(`${ENDPOINT}/${selectedParserId.value}/parse`, {
      method: 'POST',
      body: JSON.stringify({ values: { 规则id: ruleId } }),
    })
    const data = await response.json()
    parseMessage.value = data.message || (data.ok ? '解析完成' : '解析失败')
    await loadTrace()
  } catch (error) {
    parseMessage.value = error instanceof Error ? error.message : '解析失败'
  }
}

async function loadTrace() {
  parseMessage.value = ''
  try {
    const query = new URLSearchParams({ 规则编号: ruleCode.value }).toString()
    const response = await request(`${ENDPOINT}/notification?${query}`)
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || '通知溯源读取失败')
    }
    notification.value = data as Notification
  } catch (error) {
    notification.value = null
    parseMessage.value = error instanceof Error ? error.message : '通知溯源读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('解析配置列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
    if (!selectedParserId.value) {
      const htmlParser = enabledParsers.value.find((row) => row['输入格式'] === 'HTML')
      selectedParserId.value = Number((htmlParser ?? enabledParsers.value[0])?.id ?? 0)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '格式解析器列表读取失败'
  }
}

onMounted(async () => {
  await reload()
  await loadTrace()
})
</script>

<style scoped>
.detail-panel {
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
}
.detail-head h3 {
  margin: 0 0 10px;
  font-size: 15px;
}
.detail-message {
  color: var(--brand);
  font-size: 13px;
}
.filter-item select {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.closure-banner {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 14px;
  margin-bottom: 8px;
  background: #f8fafc;
}
.closure-banner.hit {
  border-color: #b42318;
  background: #fef3f2;
  color: #b42318;
  font-weight: 600;
}
.closure-text {
  display: block;
  font-weight: 400;
  font-size: 13px;
  margin-top: 4px;
}
.page-chip {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 2px 8px;
  margin-right: 6px;
  font-size: 12px;
}
.closure-row td {
  background: #fef3f2;
  color: #b42318;
}
</style>
