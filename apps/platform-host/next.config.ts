import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@goliath/ui", "@goliath/client", "@goliath/platform-ui"],
  serverExternalPackages: ["pg"],
};

export default nextConfig;
