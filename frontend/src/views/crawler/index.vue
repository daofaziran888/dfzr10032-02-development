<template>
  <section class="page" data-module="crawler">
    <header class="page-head">
      <div>
        <h2>网页采集规则管理</h2>
        <p class="page-desc">维护采集规则，围绕规则编号、目标网址、页面选择器、正文选择器做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记采集规则</button>
        <button class="btn" type="button" @click="exportRows">导出网页采集规则清单</button>
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
            <button class="link" type="button" @click="openPublish(row)">发布新版本</button>
            <button class="link" type="button" @click="openDetail(row)">快照与页面</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无网页采集规则数据，可先登记采集规则</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条网页采集规则记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section v-if="selectedRule" class="detail-panel">
      <header class="detail-head">
        <h3>发布快照与已抓页面：{{ selectedRule['规则编号'] }}</h3>
        <span class="page-desc">
          当前可执行版本：{{ currentVersion ? `v${currentVersion}` : '无（未发布或已全部回滚）' }}
        </span>
      </header>
      <p v-if="detailMessage" class="detail-message">{{ detailMessage }}</p>

      <h4 class="detail-subhead">发布快照（四要素绑定：目标网址 / 正文选择器 / 翻页参数 / 字符编码）</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in snapshotColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="snapshot in snapshots" :key="String(snapshot.id)" :class="{ 'rolled-back': snapshot.status === '已回滚' }">
            <td v-for="column in snapshotColumns" :key="column">{{ snapshot[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!snapshots.length">
            <td :colspan="snapshotColumns.length" class="empty-state">还没有发布过快照</td>
          </tr>
        </tbody>
      </table>

      <h4 class="detail-subhead">
        已抓页面（保留抓取时的快照关联，不套用新版）
        <button class="btn" type="button" @click="fetchNextPage">抓取下一页</button>
      </h4>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in pageColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pageItem in pages" :key="String(pageItem.id)">
            <td v-for="column in pageColumns" :key="column">{{ pageItem[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!pages.length">
            <td :colspan="pageColumns.length" class="empty-state">还没有抓取任何页面</td>
          </tr>
        </tbody>
      </table>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记采集规则</h3>
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

    <Teleport to="body">
      <div v-if="showPublishModal" class="modal-overlay" @click.self="showPublishModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>发布新版本：{{ publishTarget?.['规则编号'] }}</h3>
            <button class="btn ghost" type="button" @click="showPublishModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitPublish">
            <label v-for="field in snapshotFields" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="publishFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <label class="modal-check">
              <input v-model="publishSimulate" type="checkbox" />
              <span>模拟发布中断（验证重试不会拼出混合规则）</span>
            </label>
            <p class="page-desc">发布把四个要素整体绑定成一份原子快照；中断重试不会把新选择器和旧编码拼成一套可执行规则。</p>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showPublishModal = false">取消</button>
              <button class="btn primary" type="submit">整体发布</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/crawler'
const columns = ["规则编号", "目标网址", "页面选择器", "正文选择器", "翻页参数", "抓取频率", "字符编码", "去重策略"]
const actions = ["提交测试", "发布规则", "停用规则"]
const statuses = ["草稿", "测试中", "已发布", "已停用"]
const stats = [{"label": "规则总数", "value": 0}, {"label": "已发布规则", "value": 0}, {"label": "测试中规则", "value": 0}]
const snapshotFields = ["目标网址", "正文选择器", "翻页参数", "字符编码"]
const snapshotColumns = ["快照编号", "版本号", "目标网址", "正文选择器", "翻页参数", "字符编码", "发布时间", "status"]
const pageColumns = ["页面编号", "页码", "快照版本", "页面网址", "字节数", "抓取时间"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

const selectedRule = ref<Row | null>(null)
const snapshots = ref<Row[]>([])
const pages = ref<Row[]>([])
const currentVersion = ref<number | null>(null)
const detailMessage = ref('')
const showPublishModal = ref(false)
const publishTarget = ref<Row | null>(null)
const publishFields = ref<Record<string, string>>({})
const publishSimulate = ref(false)

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
      throw new Error(data.message || '网页采集规则动作未生效，请稍后重试')
    }
    await reload()
    if (selectedRule.value && selectedRule.value.id === row.id) {
      await loadDetail()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '网页采集规则操作失败'
  }
}

function openPublish(row: Row) {
  errorMessage.value = ''
  publishTarget.value = row
  publishFields.value = Object.fromEntries(snapshotFields.map((field) => [field, String(row[field] ?? '')]))
  publishSimulate.value = false
  showPublishModal.value = true
}

async function submitPublish() {
  errorMessage.value = ''
  const target = publishTarget.value
  if (!target) return
  try {
    const response = await request(`${ENDPOINT}/${target.id}/publish`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...publishFields.value, 模拟中断: publishSimulate.value ? '是' : '' } }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) {
      throw new Error(data.message || '发布失败')
    }
    showPublishModal.value = false
    detailMessage.value = data.message || '已发布'
    await reload()
    if (selectedRule.value && selectedRule.value.id === target.id) {
      await loadDetail()
    } else {
      await openDetail(target)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布失败'
  }
}

async function openDetail(row: Row) {
  selectedRule.value = row
  detailMessage.value = ''
  await loadDetail()
}

async function loadDetail() {
  const rule = selectedRule.value
  if (!rule) return
  try {
    const [snapshotResp, pageResp] = await Promise.all([
      request(`${ENDPOINT}/${rule.id}/snapshots`),
      request(`${ENDPOINT}/${rule.id}/pages`),
    ])
    const snapshotData = await snapshotResp.json()
    const pageData = await pageResp.json()
    snapshots.value = snapshotData.items ?? []
    currentVersion.value = snapshotData['当前可执行版本'] ?? null
    pages.value = pageData.items ?? []
  } catch (error) {
    detailMessage.value = error instanceof Error ? error.message : '快照与页面读取失败'
  }
}

async function fetchNextPage() {
  const rule = selectedRule.value
  if (!rule) return
  detailMessage.value = ''
  const nextPage = pages.value.reduce((max, p) => Math.max(max, Number(p['页码']) || 0), 0) + 1
  try {
    const response = await request(`${ENDPOINT}/${rule.id}/fetch`, {
      method: 'POST',
      body: JSON.stringify({ values: { 页码: nextPage } }),
    })
    const data = await response.json()
    detailMessage.value = data.message || (data.ok ? '抓取完成' : '抓取失败')
    await loadDetail()
  } catch (error) {
    detailMessage.value = error instanceof Error ? error.message : '抓取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('采集规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '网页采集规则列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.detail-panel {
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.detail-head h3 {
  margin: 0;
  font-size: 15px;
}
.detail-subhead {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--muted);
  margin: 14px 0 8px;
}
.detail-message {
  color: var(--brand);
  font-size: 13px;
}
.rolled-back td {
  color: var(--muted);
  text-decoration: line-through;
}
.modal-check {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
  color: var(--muted);
}
</style>
