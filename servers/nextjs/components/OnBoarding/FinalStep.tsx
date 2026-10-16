import { ArrowRight, PartyPopper } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useEffect } from 'react'
import confetti from 'canvas-confetti';

const CONFETTI_COLORS = ['#ff00c5', '#f3ff00', '#9500d0', '#00d2f2', '#00ea9b', '#ff7f36'];

function fireRealisticConfetti() {
    confetti({
        particleCount: 300,
        spread: 360,
        origin: { x: 0.5, y: 0.5 },
        colors: CONFETTI_COLORS,
        startVelocity: 60,
        scalar: 1.8,
        gravity: 0.6,
        ticks: 300,
        decay: 0.93,
        zIndex: 9999,
    });
}

const FinalStep = () => {
    const router = useRouter()

    useEffect(() => {
        fireRealisticConfetti();
    }, []);

    const handleGoToDashboard = () => {
        router.push('/dashboard')
    }
    const handleGoToUpload = () => {
        router.push('/upload')
    }
    return (
        <div className='fixed top-0 left-0 w-full h-full flex flex-col items-center justify-center'>
            <div className='flex flex-col items-center justify-center'>

                <img src="/final_onboarding.png" alt="presenton" className='w-[118px] h-[98px]  object-contain' />
                <h1 className='text-black text-[30px] font-normal font-unbounded py-2.5'>Welcome on board!</h1>
                <p className='text-[#000000CC] text-xl font-normal font-syne'>You’re all set. Let’s create your first presentation.</p>

                <button onClick={handleGoToUpload} className='bg-[#7C51F8] px-[23px] mt-8 py-[15px]  rounded-[70px] text-white text-lg font-syne font-semibold'>My First Presentation 🚀</button>
                <button onClick={fireRealisticConfetti} className='mt-3 flex items-center gap-1.5 text-sm text-[#7A5AF8] font-syne font-medium hover:underline'>
                    <PartyPopper className='w-4 h-4' /> Celebrate again!
                </button>
            </div>
            <button onClick={handleGoToDashboard} className='absolute uppercase bottom-20 text-[#7A5AF8] flex items-center gap-2 right-10  text-xs font-normal font-syne'>Go to your dashboard <ArrowRight className='w-4 h-4 text-[#7A5AF8]' /></button>
        </div>
    )
}

export default FinalStep
