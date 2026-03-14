"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";

export default function AuthCheck({ children }: { children: React.ReactNode }) {
    const router = useRouter();
    const pathname = usePathname();

    useEffect(() => {
        const token = localStorage.getItem("token");
        const userJson = localStorage.getItem("user");

        const publicPaths = ["/login", "/signup"];
        const isPublicPath = publicPaths.includes(pathname);

        if (!token || !userJson) {
            if (!isPublicPath) {
                router.push("/login");
            }
        } else {
            if (isPublicPath) {
                try {
                    const user = JSON.parse(userJson);
                    if (user.role === "ta") {
                        router.push("/admin/dashboard");
                    } else {
                        router.push("/student/dashboard");
                    }
                } catch (e) {
                    localStorage.clear();
                    router.push("/login");
                }
            }
        }
    }, [pathname, router]);

    return <>{children}</>;
}
