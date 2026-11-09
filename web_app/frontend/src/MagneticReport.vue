<script setup lang="ts">
import type { Spec } from './types';
defineProps<{ report: Spec }>();
const states: Record<string, string> = {success: '通过', danger: '超限', warning: '待复核'};
</script>

<template>
  <section class="card magnetic-report">
    <header class="card-heading"><h3>{{ report.title }}</h3></header>
    <p class="muted">{{ report.summary }}</p>
    <div class="magnetic-conclusions">
      <article v-for="(item, index) in report.conclusions" :key="index" :class="item.state">
        <strong>{{ states[item.state] }} · {{ item.device }} · {{ item.title }}</strong>
        <p>{{ item.detail }}</p>
      </article>
    </div>
    <div class="magnetic-sections">
      <section v-for="group in report.sections" :key="group.title" class="magnetic-group">
        <h4>{{ group.title }}</h4>
        <dl>
          <template v-for="row in group.rows" :key="row.label">
            <dt>{{ row.label }}</dt><dd><strong>{{ row.value }}</strong><span>{{ row.unit }}</span></dd>
          </template>
        </dl>
        <p v-if="group.note" class="card-note">{{ group.note }}</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.magnetic-report { margin-block: 16px; }
.magnetic-conclusions, .magnetic-sections { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 16px; }
.magnetic-conclusions { margin: 18px 0 24px; }
.magnetic-conclusions article { border: 1px solid currentColor; border-radius: 10px; padding: 14px 16px; }
.magnetic-conclusions p { margin: 8px 0 0; font-size: .94em; font-weight: 700; line-height: 1.65; overflow-wrap: anywhere; }
.success { color: #12724c; background: #f0faf5; }
.danger { color: #b42318; background: #fff3f1; }
.warning { color: #956000; background: #fffbef; }
.magnetic-group { background: #f8fafc; border: 1px solid #e1e8f0; border-radius: 10px; padding: 18px; min-width: 0; }
.magnetic-group h4 { color: #1558b0; margin: 0 0 16px; font-size: 1em; }
dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0 16px; margin: 0; }
dt, dd { margin: 0; padding: 9px 0; border-bottom: 1px solid #e4eaf0; overflow-wrap: anywhere; line-height: 1.5; }
dt { color: #5b6878; }
dd { text-align: right; font-variant-numeric: tabular-nums; }
dd span { margin-left: .5em; color: #627388; white-space: normal; }
.card-note { margin: 14px 0 0; line-height: 1.7; }
</style>
