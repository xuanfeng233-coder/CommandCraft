import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import { installSeoGuard } from './router/seo'
import App from './App.vue'
import './assets/styles/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
installSeoGuard(router)
app.mount('#app')
