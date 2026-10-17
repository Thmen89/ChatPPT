import React from 'react'
import { UserRound, Users } from 'lucide-react'
import { IMAGE_PROVIDERS, LLM_PROVIDERS } from '@/utils/providerConstants'
import { useSelector } from 'react-redux'
import { RootState } from '@/store/store'
import { cn } from '@/lib/utils'

export type SettingsSection = 'text-provider' | 'image-provider' | 'session' | 'users'

const SettingSideBar = ({
    selectedProvider,
    setSelectedProvider,
    isAdmin = false,
}: {
    selectedProvider: SettingsSection
    setSelectedProvider: (provider: SettingsSection) => void
    isAdmin?: boolean
}) => {
    const { llm_config } = useSelector((state: RootState) => state.userConfig)
    const textIcon = LLM_PROVIDERS[llm_config.LLM as keyof typeof LLM_PROVIDERS]?.icon
    const imageIcon = IMAGE_PROVIDERS[llm_config.IMAGE_PROVIDER as keyof typeof IMAGE_PROVIDERS]?.icon || '/providers/pexel.png'
    const items: { id: SettingsSection; label: string; icon: React.ReactNode }[] = [
        { id: 'text-provider', label: 'Text model', icon: <img src={textIcon} alt="" className="h-4 w-4 rounded-full object-cover" /> },
        { id: 'image-provider', label: 'Images', icon: <img src={imageIcon} alt="" className="h-4 w-4 rounded-full object-cover" /> },
        { id: 'session', label: 'Account & tokens', icon: <UserRound className="h-3.5 w-3.5 text-zinc-500" /> },
    ]
    if (isAdmin) {
        items.push({ id: 'users', label: 'Users', icon: <Users className="h-3.5 w-3.5 text-zinc-500" /> })
    }
    return (
        <nav aria-label="Settings sections" className="w-[180px] shrink-0">
            <ul className="space-y-0.5">
                {items.map((item) => (
                    <li key={item.id}>
                        <button
                            type="button"
                            aria-current={selectedProvider === item.id ? 'page' : undefined}
                            onClick={() => setSelectedProvider(item.id)}
                            className={cn(
                                'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px]',
                                selectedProvider === item.id ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-600 hover:text-zinc-900'
                            )}
                        >
                            {item.icon}
                            {item.label}
                        </button>
                    </li>
                ))}
            </ul>
        </nav>
    )
}

export default SettingSideBar
