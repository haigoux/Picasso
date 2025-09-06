import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@/assets/main.scss'
import App from './App.vue'
import router from './router'
import cookie from 'cookiejs'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.config.globalProperties.$cookie = cookie

app.mount('#app')
