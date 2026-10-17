import { redirect } from "next/navigation";
import AuthGate from "@/components/Auth/AuthGate";
import { isAuthDisabled } from "@/utils/auth";
import { getServerAuthStatus } from "@/utils/serverAuth";

// The prompt box is the home screen. A missing model is handled there (it sends you to
// Settings), so there is no onboarding.
const page = async () => {
    if (isAuthDisabled()) {
        redirect("/upload");
    }

    const status = await getServerAuthStatus();
    if (status.configured && status.authenticated) {
        redirect("/upload");
    }

    return <AuthGate />;
};

export default page;
