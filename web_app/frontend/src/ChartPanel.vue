<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, inject } from "vue";
import { getBlob } from "./api";
import Icon from "./Icon.vue";
const modalTarget=inject<HTMLElement|string>('power-modal-target','body');
const props = withDefaults(
  defineProps<{
    job: string;
    caseId: string;
    kind: string;
    title: string;
    output?: number;
    note?: string;
  }>(),
  { output: 1 },
);
const image = ref(""),
  error = ref(""),
  loading = ref(false),
  expanded = ref(false);
const container = ref<HTMLElement>(),
  visible = ref(false);
let observer: IntersectionObserver | undefined;
let controller: AbortController | undefined,
  revision = 0;
async function load() {
  const current = ++revision;
  controller?.abort();
  controller = new AbortController();
  if (image.value) URL.revokeObjectURL(image.value);
  image.value = "";
  error.value = "";
  loading.value = true;
  try {
    const blob = await getBlob(
      `/jobs/${props.job}/chart/${props.kind}?case=${props.caseId}&output=${props.output}`,
      controller.signal,
    );
    if (current === revision) image.value = URL.createObjectURL(blob);
  } catch (e: any) {
    if (current === revision && e.name !== "AbortError")
      error.value = e.message;
  } finally {
    if (current === revision) loading.value = false;
  }
}
watch(
  () => [props.job, props.caseId, props.kind, props.output],
  () => {
    if (visible.value) void load();
  },
);
onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        visible.value = true;
        observer?.disconnect();
        void load();
      }
    },
    { rootMargin: "500px" },
  );
  if (container.value) observer.observe(container.value);
});
onBeforeUnmount(() => {
  revision++;
  observer?.disconnect();
  controller?.abort();
  if (image.value) URL.revokeObjectURL(image.value);
});
</script>
<template>
  <section ref="container" class="card chart-card">
    <div class="card-heading">
      <h3>{{ title }}</h3>
      <button
        v-if="image"
        class="icon-button"
        title="放大图表"
        @click="expanded = true"
      >
        <Icon name="expand" :size="16" />
      </button>
    </div>
    <div v-if="!visible" class="chart-loading">滚动到此处后按需绘图</div>
    <div v-else-if="loading" class="chart-loading">
      <span class="spinner" />正在绘制当前快照…
    </div>
    <div v-else-if="error" class="chart-error">
      <Icon name="info" />{{ error
      }}<button class="text-button" @click="load">重试</button>
    </div>
    <img
      v-else-if="image"
      :src="image"
      :alt="title"
      class="chart-image"
      @click="expanded = true"
    />
    <p v-if="note" class="chart-note">{{ note }}</p>
  </section>
  <Teleport :to="modalTarget"
    ><div v-if="expanded" class="modal-backdrop" @click.self="expanded = false">
      <section class="modal chart-modal">
        <header>
          <h3>{{ title }} · {{ caseId }}</h3>
          <button
            class="icon-button"
            aria-label="关闭图表"
            @click="expanded = false"
          >
            <Icon name="close" />
          </button>
        </header>
        <img :src="image" :alt="title" />
      </section></div
  ></Teleport>
</template>
