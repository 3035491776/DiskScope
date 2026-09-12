<template>
  <section class="panel low-impact-card" aria-labelledby="low-impact-title">
    <div class="panel-heading"><div><p class="eyebrow">只读保障</p><h2 id="low-impact-title">Low-Impact Scan</h2></div><span class="safe-badge">已启用</span></div>
    <div class="policy-grid">
      <div><span>文件元数据</span><strong>仅此范围</strong></div>
      <div><span>扫描并发</span><strong>1</strong></div>
      <div><span>链接与挂载点</span><strong>不跟随</strong></div>
      <div><span>跨卷扫描</span><strong>禁止</strong></div>
      <div><span>整卷扫描</span><strong>锁定</strong></div>
      <div><span>文件正文</span><strong>不读取</strong></div>
    </div>
    <details class="policy-details"><summary>为什么这样扫描？</summary><p>DiskScope 只读取目录和文件的大小等元数据，每次只有一个扫描任务，尽量减少对日常使用的影响。当前不允许扫描整个 C: 或 D: 卷。</p></details>
  </section>
</template>
