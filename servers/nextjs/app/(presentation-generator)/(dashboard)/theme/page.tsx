import React, { Suspense } from 'react'
import ThemePanel from './components/ThemePanel'
const page = () => {
    return (
        <Suspense>
            <ThemePanel />
        </Suspense>
    )
}

export default page