import { shallowRef } from 'vue'
import type { RiskProfile } from './api/m4'

// 仅在本次登录期间传递画像依据，不保存到浏览器持久存储。
export const governanceProfile = shallowRef<RiskProfile | null>(null)
export function resetWorkspace() { governanceProfile.value = null }
