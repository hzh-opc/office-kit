# -*- coding: utf-8 -*-
"""生成《版面美学观》响应式 HTML 参考（本身即移动优先、多终端自适应演示）。"""
import argparse, os

DEFAULT_OUT_DIR = os.getcwd()  # 平台无关：默认输出当前目录，可用 --out 覆盖

HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>版面美学观 · 响应式参考（手机/平板/桌面）</title>
<style>
  :root{
    --bg:#f6f7f9; --surface:#ffffff; --ink:#1a1a1a; --muted:#5a5f66;
    --line:#e4e7ec; --accent:#1a5fb4; --accent-soft:#e8f0fb;
    --good:#0a7d3f; --good-soft:#e6f4ea; --bad:#b00020; --bad-soft:#fbe9ec;
    --radius:14px; --shadow:0 1px 3px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.05);
  }
  *{box-sizing:border-box;}
  html{-webkit-text-size-adjust:100%;}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Source Han Sans SC","Noto Sans CJK SC","Noto Sans SC",-apple-system,BlinkMacSystemFont,sans-serif;
    line-height:1.75; font-size:clamp(15px,.95rem + .3vw,17px);
    padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
  }
  a{color:var(--accent);text-decoration:none;}
  .wrap{max-width:78ch;margin:0 auto;padding:0 clamp(16px,4vw,32px);}

  /* 顶部导航：移动端横向滚动 */
  nav{
    position:sticky;top:0;z-index:10;background:rgba(246,247,249,.92);
    backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
  }
  nav .nav-inner{display:flex;gap:6px;overflow-x:auto;padding:10px clamp(16px,4vw,32px);
    scrollbar-width:none;-webkit-overflow-scrolling:touch;}
  nav .nav-inner::-webkit-scrollbar{display:none;}
  nav a{flex:0 0 auto;padding:6px 12px;border-radius:999px;font-size:14px;color:var(--muted);
    border:1px solid transparent;white-space:nowrap;}
  nav a:hover{color:var(--ink);background:var(--surface);border-color:var(--line);}

  header.hero{padding:clamp(36px,7vw,72px) 0 clamp(20px,4vw,36px);}
  header.hero h1{
    font-size:clamp(28px,2rem + 3vw,48px);line-height:1.15;margin:0 0 12px;
    letter-spacing:.5px;
  }
  header.hero p{color:var(--muted);font-size:clamp(15px,1rem + .2vw,18px);margin:0;max-width:60ch;}

  section{padding:clamp(28px,5vw,48px) 0;}
  h2{font-size:clamp(20px,1.3rem + 1vw,28px);margin:0 0 6px;}
  h3{font-size:clamp(16px,1.1rem + .3vw,20px);margin:28px 0 10px;}
  .lead{color:var(--muted);margin:0 0 18px;max-width:65ch;}

  /* 媒介卡片：移动1列 / 平板2列 / 桌面4列 */
  .grid{display:grid;gap:16px;grid-template-columns:1fr;}
  @media(min-width:640px){.grid{grid-template-columns:repeat(2,1fr);}}
  @media(min-width:1024px){.grid{grid-template-columns:repeat(4,1fr);}}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    padding:18px;box-shadow:var(--shadow);}
  .card h4{margin:0 0 8px;font-size:17px;}
  .card .tag{display:inline-block;font-size:12px;color:var(--accent);background:var(--accent-soft);
    padding:2px 8px;border-radius:999px;margin-bottom:8px;}
  .card ul{margin:0;padding-left:18px;color:var(--muted);font-size:14px;}
  .card ul li{margin:4px 0;}

  /* 表格：移动端横向滚动 */
  .table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);
    border-radius:var(--radius);background:var(--surface);box-shadow:var(--shadow);}
  table{border-collapse:collapse;width:100%;min-width:560px;font-size:14px;}
  th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);}
  thead th{background:#eef2f7;position:sticky;top:0;}
  tbody tr:last-child td{border-bottom:none;}
  td .sub{color:var(--muted);font-size:12px;}

  .two-col{display:grid;gap:16px;grid-template-columns:1fr;}
  @media(min-width:860px){.two-col{grid-template-columns:1fr 1fr;}}

  /* 终端预览：用容器查询让同一内容在三种宽度下真实重排 */
  .devices{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start;}
  .device{flex:1 1 280px;min-width:0;background:var(--surface);border:1px solid var(--line);
    border-radius:18px;padding:12px;box-shadow:var(--shadow);}
  .device .label{font-size:12px;color:var(--muted);text-align:center;margin-bottom:8px;}
  .screen{border:1px solid var(--line);border-radius:10px;background:var(--bg);
    overflow:hidden;container-type:inline-size;padding:12px;}
  .mock-head{font-weight:700;font-size:15px;margin:0 0 8px;}
  .mock-grid{display:grid;grid-template-columns:1fr;gap:8px;}
  @container(min-width:300px){.mock-grid{grid-template-columns:1fr 1fr;}}
  @container(min-width:520px){.mock-grid{grid-template-columns:repeat(3,1fr);}}
  .mock-item{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px;font-size:12px;color:var(--muted);}
  .mock-cta{display:inline-flex;align-items:center;justify-content:center;min-height:44px;
    margin-top:10px;padding:0 16px;background:var(--accent);color:#fff;border-radius:10px;font-size:13px;width:100%;}

  .callout{border-left:3px solid var(--accent);background:var(--accent-soft);
    padding:12px 16px;border-radius:0 10px 10px 0;color:#143a63;font-size:14px;}
  footer{padding:32px 0 56px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);margin-top:24px;}

  @media(prefers-reduced-motion:reduce){
    *{animation:none!important;transition:none!important;}
  }
</style>
</head>
<body>

<nav>
  <div class="nav-inner">
    <a href="#intro">概览</a>
    <a href="#media">四大媒介</a>
    <a href="#paper">纸型·手账</a>
    <a href="#web">网页</a>
    <a href="#slide">幻灯片</a>
    <a href="#terminal">多终端</a>
    <a href="#preview">终端预览</a>
  </div>
</nav>

<header class="hero">
  <div class="wrap">
    <h1>版面美学观 · 响应式参考</h1>
    <p>侯捷《Word 排版艺术》的七大原则，扩展至常见纸型（含手账）、网页、幻灯片与平板 / 手机多终端。本页本身即移动优先、响应式，可直接在手机上阅读。</p>
  </div>
</header>

<div class="wrap">

  <section id="intro">
    <h2>一、核心原则（跨媒介通用）</h2>
    <p class="lead">对齐 / 对比 / 亲密性 / 重复 / 留白 / 节制 / 中英文混排——七条原则在文档、网页、幻灯片、手账上一致成立，只是参数随媒介变化。</p>
    <div class="grid">
      <div class="card"><h4>对齐</h4><ul><li>元素不随意摆放</li><li>正文两端对齐(纯中文)/左对齐(混排)</li></ul></div>
      <div class="card"><h4>对比</h4><ul><li>不同就截然不同</li><li>字号/字重/颜色制造焦点</li></ul></div>
      <div class="card"><h4>亲密性</h4><ul><li>相关内容成组</li><li>无关以留白区隔</li></ul></div>
      <div class="card"><h4>重复</h4><ul><li>字体/颜色/线宽全文一致</li><li>用样式固化</li></ul></div>
      <div class="card"><h4>留白</h4><ul><li>给版面呼吸感</li><li>页边距/段距/行距服务留白</li></ul></div>
      <div class="card"><h4>节制</h4><ul><li>字体≤3 种</li><li>颜色≤主色+3 辅助</li></ul></div>
      <div class="card"><h4>中英文混排</h4><ul><li>英文小 1~2pt</li><li>中英间加半角空格</li></ul></div>
      <div class="card"><h4>态度</h4><ul><li>掌控每一样东西</li><li>样式是理论基石</li></ul></div>
    </div>
  </section>

  <section id="media">
    <h2>二、四大媒介速查</h2>
    <p class="lead">先定媒介，再选参数。同一原则落到不同载体，差异主要在版心、字号与信息密度。</p>
    <div class="grid">
      <div class="card"><span class="tag">文档 / 手账</span><h4>纸型与版心</h4><ul><li>A4 报告；A5/A6 笔记</li><li>手账内边≥8mm</li><li>正文 12pt，行距 1.5</li></ul></div>
      <div class="card"><span class="tag">网页</span><h4>流动版心</h4><ul><li>max-width 65~75ch</li><li>clamp 流式字号</li><li>移动优先 + 断点</li></ul></div>
      <div class="card"><span class="tag">幻灯片</span><h4>远距阅读</h4><ul><li>16:9，字号≥18pt</li><li>每页一观点</li><li>安全区≥0.5in</li></ul></div>
      <div class="card"><span class="tag">手机 / 平板</span><h4>多终端</h4><ul><li>视口 meta 必备</li><li>触控≥44px</li><li>clamp 平滑缩放</li></ul></div>
    </div>
  </section>

  <section id="paper">
    <h2>三、常见纸型（含手账）</h2>
    <p class="lead">页边距随纸型缩小而收紧，版心占比稳定。手账以格线为对齐基准，用色块分区而非大字号。</p>
    <div class="table-scroll">
      <table>
        <thead><tr><th>纸型</th><th>尺寸(mm)</th><th>用途</th><th>推荐页边距</th></tr></thead>
        <tbody>
          <tr><td>A4</td><td>210×297</td><td>报告/论文/合同</td><td>上下2.54，左右3.17(装订+2)</td></tr>
          <tr><td>A5</td><td>148×210</td><td>小册子/笔记</td><td>上下1.5，左右1.5</td></tr>
          <tr><td>A6</td><td>105×148</td><td>便签/手账页</td><td>上下1.0，左右1.0</td></tr>
          <tr><td>B5</td><td>176×250</td><td>书籍/杂志</td><td>上下2.0，左右2.0</td></tr>
          <tr><td>16开</td><td>184×260</td><td>中文图书</td><td>上下2.0，左右2.0</td></tr>
          <tr><td>Letter</td><td>215.9×279.4</td><td>北美通用</td><td>上下2.54，左右2.54</td></tr>
          <tr><td>名片</td><td>90×54</td><td>名片</td><td>上下5，左右5(mm)</td></tr>
          <tr><td>手账·Hobonichi A6</td><td>105×148</td><td>日程手账</td><td>内边≥8</td></tr>
          <tr><td>手账·Traveler's</td><td>110×210</td><td>旅行手账</td><td>内边≥8</td></tr>
          <tr><td>手账·TN Passport</td><td>124×89</td><td>护照尺寸</td><td>内边≥6</td></tr>
          <tr><td>手账·Moleskine 口袋</td><td>90×140</td><td>随身本</td><td>内边≥8</td></tr>
        </tbody>
      </table>
    </div>
    <div class="callout" style="margin-top:16px;">手账要点：版心小、留白多；字号 8~10pt、行距 1.2~1.3；用色块/胶带/贴纸分区；照片与文字成组相邻，避免满版。</div>
  </section>

  <section id="web">
    <h2>四、网页排版（响应式）</h2>
    <div class="two-col">
      <div class="card"><h4>版心与字号</h4><ul><li>max-width 65~75ch，中文每行 35~45 字</li><li>clamp(1rem, .9rem+.4vw, 1.125rem)，根 16px</li><li>行距 1.6~1.8，段距 1~1.5em</li></ul></div>
      <div class="card"><h4>断点与栅格</h4><ul><li>手机&lt;640 / 平板 640~1024 / 桌面&gt;1024</li><li>移动优先：先手机再 min-width 增强</li><li>Grid auto-fit minmax(280px,1fr)</li></ul></div>
      <div class="card"><h4>对比与深色</h4><ul><li>正文≥WCAG AA(4.5:1)</li><li>CSS 变量管主色+辅助色</li><li>prefers-color-scheme:dark 切换</li></ul></div>
      <div class="card"><h4>可达性</h4><ul><li>焦点态可见、语义标签</li><li>图片替代文本</li><li>prefers-reduced-motion 关动效</li></ul></div>
    </div>
  </section>

  <section id="slide">
    <h2>五、幻灯片排版</h2>
    <div class="two-col">
      <div class="card"><h4>画幅与字号</h4><ul><li>16:9(254×190.5mm) 默认</li><li>标题 36~44pt，正文 24~28pt</li><li>最小≥18pt（后排可读）</li></ul></div>
      <div class="card"><h4>信息密度</h4><ul><li>每页一个观点</li><li>正文≤6 行、每行≤30 字</li><li>讲稿放备注，不堆屏</li></ul></div>
      <div class="card"><h4>版式</h4><ul><li>安全区≥0.5in 防裁切</li><li>左对齐为主，对齐隐式网格</li><li>深浅背景+单一强调色</li></ul></div>
      <div class="card"><h4>图与动效</h4><ul><li>object-fit:cover 不变形</li><li>图表大号、去冗余网格线</li><li>动效仅分步揭示</li></ul></div>
    </div>
  </section>

  <section id="terminal">
    <h2>六、多终端显示优化（平板 / 手机）</h2>
    <div class="grid">
      <div class="card"><h4>视口与移动优先</h4><ul><li>viewport meta 必备</li><li>先手机样式，min-width 增强</li><li>不写死 px 宽度</li></ul></div>
      <div class="card"><h4>触控目标</h4><ul><li>可点元素≥44×44px</li><li>间距充足防误触</li><li>Apple HIG / Material</li></ul></div>
      <div class="card"><h4>流式与安全区</h4><ul><li>clamp() 320~1440px 缩放</li><li>env(safe-area-inset-*)</li><li>适配刘海/圆角</li></ul></div>
      <div class="card"><h4>资源与可读</h4><ul><li>srcset+sizes 按 DPR 加载</li><li>移动端每行 30~40 汉字</li><li>系统字体栈免下载</li></ul></div>
    </div>
  </section>

  <section id="preview">
    <h2>七、终端预览（同一内容三种宽度）</h2>
    <p class="lead">下方三个「设备」用 CSS 容器查询分别约束宽度，内部同一卡片会在手机(1列)、平板(2列)、桌面(3列)下真实重排——这就是多终端优化的核心：一套结构，多端自适应。</p>
    <div class="devices">
      <div class="device">
        <div class="label">手机 · 320px</div>
        <div class="screen">
          <p class="mock-head">版面美学</p>
          <div class="mock-grid">
            <div class="mock-item">对齐统一</div>
            <div class="mock-item">对比焦点</div>
            <div class="mock-item">亲密成组</div>
            <div class="mock-item">重复节奏</div>
            <div class="mock-item">留白呼吸</div>
            <div class="mock-item">节制字体</div>
          </div>
          <div class="mock-cta">查看完整规范</div>
        </div>
      </div>
      <div class="device">
        <div class="label">平板 · 720px</div>
        <div class="screen">
          <p class="mock-head">版面美学</p>
          <div class="mock-grid">
            <div class="mock-item">对齐统一</div>
            <div class="mock-item">对比焦点</div>
            <div class="mock-item">亲密成组</div>
            <div class="mock-item">重复节奏</div>
            <div class="mock-item">留白呼吸</div>
            <div class="mock-item">节制字体</div>
          </div>
          <div class="mock-cta">查看完整规范</div>
        </div>
      </div>
      <div class="device">
        <div class="label">桌面 · 1000px</div>
        <div class="screen">
          <p class="mock-head">版面美学</p>
          <div class="mock-grid">
            <div class="mock-item">对齐统一</div>
            <div class="mock-item">对比焦点</div>
            <div class="mock-item">亲密成组</div>
            <div class="mock-item">重复节奏</div>
            <div class="mock-item">留白呼吸</div>
            <div class="mock-item">节制字体</div>
          </div>
          <div class="mock-cta">查看完整规范</div>
        </div>
      </div>
    </div>
  </section>

  <footer>
    来源：侯捷《Word 排版艺术》（电子工业出版社，2004）。本页为技能 <code>doc-layout-aesthetics</code> 的跨媒介演示，本身即响应式、移动优先。
  </footer>

</div>
</body>
</html>
'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="输出目录（默认当前目录）")
    args = ap.parse_args()
    out_dir = args.out or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "版面美学观_响应式参考.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(HTML)
    print("saved:", path, "| bytes:", len(HTML))

if __name__ == "__main__":
    main()
