// render_pdf.swift — macOS 原生 PDF 高保真渲染器（PDF → PNG）
//
// 用途：把生成的 PDF 渲染成 PNG 图片，用于人工视觉核验排版效果。
// 为什么用它：macOS 的 sips / qlmanage 对 reportlab 子集化字体会缺字形，无法
//   如实反映字间距/对齐；本工具走 PDFKit + CoreGraphics（系统原生渲染管线），
//   与 Preview / 快速查看一致，能高保真还原版面。
//
// 平台边界：**仅 macOS**（依赖 PDFKit / AppKit / CoreGraphics）。
//   Linux / Windows 无此脚本的等价物——在那些平台做视觉核验请改用
//   build_md_pdf.py 生成的 PDF 直接在本地 PDF 阅读器打开。
//
// 依赖：无第三方包，仅 macOS 系统自带的 swift + 系统框架。
//
// 用法：
//   swift scripts/render_pdf.swift <input.pdf>                     # 第 1 页 -> 同目录 <base>.png
//   swift scripts/render_pdf.swift <input.pdf> -o out.png -p 2    # 第 3 页 -> out.png
//   swift scripts/render_pdf.swift <input.pdf> --all -s 1.4       # 全部页 -> <base>_pages/page_01.png ...
//
// 参数：
//   -o, --out <path>   输出 PNG 路径（单页）或目录（--all），默认 <input>.png / <input>_pages/
//   -p, --page <n>     渲染第 n 页（0 起，默认 0）
//   --all              渲染全部页面
//   -s, --scale <f>    缩放倍率（默认 1.5；A4 @1.5 ≈ 1240×1754 px）
//   -h, --help         帮助

import Foundation
import PDFKit
import AppKit
import CoreGraphics

// ---------- 参数解析 ----------
let argv = CommandLine.arguments
let prog = (argv.first as NSString?)?.lastPathComponent ?? "render_pdf.swift"

func usage() -> Never {
    print("""
    macOS 原生 PDF 高保真渲染器（仅 macOS）
    用法:
      swift \(prog) <input.pdf> [选项]
    选项:
      -o, --out <path>   输出 PNG（单页）或目录（--all 时），默认 <input>.png / <input>_pages/
      -p, --page <n>     渲染第 n 页（0 起，默认 0）
      --all              渲染全部页面
      -s, --scale <f>    缩放倍率（默认 1.5）
      -h, --help         帮助
    """)
    exit(1)
}

var inputPath: String?
var outPath: String?
var pageIndex = 0
var allPages = false
var scale: CGFloat = 1.5

var i = 1
while i < argv.count {
    let a = argv[i]
    switch a {
    case "-h", "--help":
        usage()
    case "-o", "--out":
        i += 1
        if i < argv.count { outPath = argv[i] } else { usage() }
    case "-p", "--page":
        i += 1
        if i < argv.count, let n = Int(argv[i]) { pageIndex = n } else { usage() }
    case "--all":
        allPages = true
    case "-s", "--scale":
        i += 1
        if i < argv.count, let f = Double(argv[i]) { scale = CGFloat(f) } else { usage() }
    default:
        if a.hasPrefix("-") { usage() }
        if inputPath == nil { inputPath = a } else { usage() }
    }
    i += 1
}
guard let inputPath = inputPath else { usage() }

// ---------- 打开文档 ----------
guard let doc = PDFDocument(url: URL(fileURLWithPath: inputPath)) else {
    print("错误：无法打开 PDF \(inputPath)"); exit(1)
}
let pageCount = doc.pageCount
guard pageCount > 0 else { print("错误：PDF 无页面"); exit(1) }

func render(page: PDFPage, to path: String) -> Bool {
    let bounds = page.bounds(for: .mediaBox)
    let w = Int((bounds.width * scale).rounded())
    let h = Int((bounds.height * scale).rounded())
    guard w > 0, h > 0 else { print("错误：页面尺寸非法"); return false }
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let bitmapInfo = CGImageAlphaInfo.premultipliedLast.rawValue
    guard let ctx = CGContext(data: nil, width: w, height: h,
                              bitsPerComponent: 8, bytesPerRow: 0,
                              space: colorSpace, bitmapInfo: bitmapInfo) else {
        print("错误：创建绘图上下文失败"); return false
    }
    // 白底（PDF 透明背景页面在 PNG 里显示为白）
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    if let cgPage = page.pageRef {
        ctx.drawPDFPage(cgPage)
    }
    guard let img = ctx.makeImage() else { print("错误：生成图像失败"); return false }
    let rep = NSBitmapImageRep(cgImage: img)
    rep.size = NSSize(width: w, height: h)
    guard let data = rep.representation(using: .png, properties: [:]) else {
        print("错误：PNG 编码失败"); return false
    }
    do {
        try data.write(to: URL(fileURLWithPath: path))
    } catch {
        print("错误：写入失败 \(path): \(error.localizedDescription)"); return false
    }
    return true
}

// ---------- 单页 / 多页 ----------
let fm = FileManager.default
let base = (inputPath as NSString).deletingPathExtension

if allPages {
    let dir = outPath ?? (base + "_pages")
    try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)
    for idx in 0..<pageCount {
        guard let page = doc.page(at: idx) else { continue }
        let name = String(format: "page_%02d.png", idx + 1)
        let path = (dir as NSString).appendingPathComponent(name)
        if render(page: page, to: path) {
            print("rendered -> \(path)")
        }
    }
    print("共渲染 \(pageCount) 页 -> \(dir)")
} else {
    if pageIndex < 0 || pageIndex >= pageCount {
        print("错误：页码 \(pageIndex) 越界（共 \(pageCount) 页）"); exit(1)
    }
    guard let page = doc.page(at: pageIndex) else { print("错误：读取第 \(pageIndex) 页失败"); exit(1) }
    let path = outPath ?? (base + ".png")
    if render(page: page, to: path) {
        print("rendered -> \(path)")
    } else {
        exit(1)
    }
}
