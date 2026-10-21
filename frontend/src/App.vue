<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { FlaskConical, Database, ArrowUpRight, Activity, Menu, X } from 'lucide-vue-next'
import { usePolling } from './usePolling'
const route = useRoute(),
  online = ref(false),
  menu = ref(false)
usePolling(async () => {
  try {
    online.value = (await fetch('/health/ready', { signal: AbortSignal.timeout(5000) })).ok
  } catch {
    online.value = false
  }
}, 10000)
</script>
<template>
  <a class="skip-link" href="#main">Перейти к содержимому</a>
  <aside class="sidebar" :class="{ open: menu }">
    <RouterLink class="brand" to="/experiments" @click="menu = false"
      ><span class="brand-mark">m<span>c</span></span>
      <div>ML Criterion<small>Лаборатория экспериментов</small></div></RouterLink
    >
    <div class="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
    <nav aria-label="Основная навигация">
      <RouterLink
        to="/experiments"
        :class="{ selected: route.path.startsWith('/experiments') }"
        @click="menu = false"
        ><FlaskConical :size="19" /> Эксперименты</RouterLink
      >
      <RouterLink to="/datasets" @click="menu = false"><Database :size="19" /> Датасеты</RouterLink>
    </nav>
    <div class="sidebar-note">
      <div class="mini-symbol">↗</div>
      <strong>Два подхода.<br />Одни условия.</strong>
      <p>Сравнивайте обучение внутри базы данных и в Python на одинаковых выборках.</p>
      <div class="engine-dots"><span>MADlib</span><span>scikit-learn</span></div>
    </div>
    <div class="sidebar-bottom">
      <span class="connection" :class="{ online }"
        ><i></i>{{ online ? 'API подключён' : 'API недоступен' }}</span
      ><small>Локальный исследовательский стенд</small>
    </div>
  </aside>
  <button v-if="menu" class="scrim" aria-label="Закрыть меню" @click="menu = false"></button>
  <div class="workspace">
    <header class="topbar">
      <button class="icon-button mobile-menu" aria-label="Открыть меню" @click="menu = !menu">
        <X v-if="menu" :size="20" /><Menu v-else :size="20" /></button
      ><span class="breadcrumb"
        >Рабочее пространство <span>/</span>
        {{ route.path.startsWith('/datasets') ? 'Датасеты' : 'Эксперименты' }}</span
      ><a href="http://localhost:8000/docs" target="_blank" rel="noopener"
        >API документация <ArrowUpRight :size="15" /></a
      ><span class="avatar" title="Локальное рабочее пространство">ML</span>
    </header>
    <main id="main" tabindex="-1"><RouterView :key="route.fullPath" /></main>
    <footer>
      <span>ML Criterion <span class="muted">/ Воспроизводимые сравнения</span></span
      ><span><Activity :size="13" /> PostgreSQL + MADlib · Python</span>
    </footer>
  </div>
</template>
