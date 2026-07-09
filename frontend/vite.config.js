export default {
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/dist": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/uploads": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
};
