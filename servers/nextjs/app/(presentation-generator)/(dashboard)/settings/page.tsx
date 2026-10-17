import React, { Suspense } from 'react'
import SettingPage from './SettingPage'

export const metadata = {
  title: 'Settings | ChatPPT',
  description: 'Model and image providers, saved to chatppt.toml.',
}

const page = () => (
  <Suspense>
    <SettingPage />
  </Suspense>
)

export default page
