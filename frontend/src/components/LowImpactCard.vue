<template>
  <section class="panel low-impact-card" aria-labelledby="low-impact-title">
    <div class="panel-heading"><div><p class="eyebrow">安全说明</p><h2 id="low-impact-title">扫描期间不会修改你的文件</h2></div><span class="safe-badge">安全扫描</span></div>
    <div class="policy-grid">
      <div><span>读取内容</span><strong>仅文件基本信息</strong></div>
      <div><span>同时扫描</span><strong>一次一个位置</strong></div>
      <div><span>系统链接</span><strong>自动跳过</strong></div>
      <div><span>其他磁盘</span><strong>不会进入</strong></div>
      <div><span>完整磁盘</span><strong>只支持 C 盘</strong></div>
      <div><span>文件正文</span><strong>不读取</strong></div>
    </div>
    <details class="policy-details"><summary>技术详情</summary><p>DiskScope 只读取文件和文件夹的大小、时间等基本信息，每次只有一个扫描任务，不跟随系统链接，不跨磁盘，也不读取文件正文。</p></details>
  </section>
</template>
