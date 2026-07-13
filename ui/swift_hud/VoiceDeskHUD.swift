import AppKit
import SwiftUI

private struct ProviderColumn: Identifiable {
    let id = UUID()
    let title: String
    let lines: [String]
}

private struct HUDSnapshot {
    var visible = true
    var visual = "idle_collapsed"
    var state = "idle"
    var stateLabel = ""
    var stateColor = NSColor.white
    var baseWidth: CGFloat = 340
    var baseHeight: CGFloat = 64
    var providerSummary = ""
    var providerColumns: [ProviderColumn] = []
    var transcript = ""
    var micBars: [CGFloat] = []
    var showClock = true
    var showMedia = true
    var clockTime = ""
    var clockDate = ""
    var mediaTitle = ""
    var mediaArtist = ""
    var mediaPlaying = false
    var mediaArtwork = ""     // base64 PNG
    var mediaPlayerApp = ""   // "Music" | "Spotify" | "" — which app to control
    var routines: [String] = []
    var battery = ""
    var batteryPercent: Int? = nil
    var batteryCharging = false
    var interactionSounds = true
    var inputPrompt = ""
    var inputPrefill = ""

    init() {}

    init(_ raw: [String: Any]) {
        visible = bool(raw["visible"], true)
        visual = string(raw["visual"], "idle_collapsed")
        state = string(raw["state"], "idle")
        stateLabel = string(raw["stateLabel"], "")
        stateColor = color(raw["stateColor"], NSColor.white)
        baseWidth = cgFloat(raw["baseWidth"], 340)
        baseHeight = cgFloat(raw["baseHeight"], 64)
        providerSummary = string(raw["providerSummary"], "")
        transcript = string(raw["transcript"], "")
        micBars = cgFloatArray(raw["micBars"])
        showClock = bool(raw["showClock"], true)
        showMedia = bool(raw["showMedia"], true)
        clockTime = string(raw["clockTime"], "")
        clockDate = string(raw["clockDate"], "")
        mediaTitle = string(raw["mediaTitle"], "")
        mediaArtist = string(raw["mediaArtist"], "")
        mediaPlaying = bool(raw["mediaPlaying"], false)
        mediaArtwork = string(raw["mediaArtwork"], "")
        mediaPlayerApp = string(raw["mediaPlayerApp"], "")
        routines = stringArray(raw["routines"])
        battery = string(raw["battery"], "")
        batteryPercent = (raw["batteryPercent"] as? NSNumber)?.intValue
        batteryCharging = bool(raw["batteryCharging"], false)
        interactionSounds = bool(raw["interactionSounds"], true)
        inputPrompt = string(raw["inputPrompt"], "")
        inputPrefill = string(raw["inputPrefill"], "")

        if let cols = raw["providerColumns"] as? [[String: Any]] {
            providerColumns = cols.map {
                ProviderColumn(
                    title: string($0["title"], ""),
                    lines: stringArray($0["lines"])
                )
            }
        }
    }
}

private func string(_ value: Any?, _ fallback: String) -> String {
    value as? String ?? fallback
}

private func bool(_ value: Any?, _ fallback: Bool) -> Bool {
    if let value = value as? Bool { return value }
    if let value = value as? NSNumber { return value.boolValue }
    return fallback
}

private func cgFloat(_ value: Any?, _ fallback: CGFloat) -> CGFloat {
    if let value = value as? CGFloat { return value }
    if let value = value as? NSNumber { return CGFloat(value.doubleValue) }
    if let value = value as? Double { return CGFloat(value) }
    return fallback
}

private func cgFloatArray(_ value: Any?) -> [CGFloat] {
    guard let values = value as? [Any] else { return [] }
    return values.map { cgFloat($0, 0) }
}

private func stringArray(_ value: Any?) -> [String] {
    guard let values = value as? [Any] else { return [] }
    return values.compactMap { $0 as? String }
}

private func color(_ value: Any?, _ fallback: NSColor) -> NSColor {
    guard let values = value as? [Any], values.count >= 3 else { return fallback }
    let red = cgFloat(values[0], 1)
    let green = cgFloat(values[1], 1)
    let blue = cgFloat(values[2], 1)
    let alpha = values.count >= 4 ? cgFloat(values[3], 1) : 1
    return NSColor(calibratedRed: red, green: green, blue: blue, alpha: alpha)
}

private final class EventEmitter {
    private let lock = NSLock()

    func emit(_ event: String, _ extra: [String: Any] = [:]) {
        var payload = extra
        payload["event"] = event
        guard var data = try? JSONSerialization.data(withJSONObject: payload) else {
            return
        }
        data.append(contentsOf: [0x0A])
        lock.lock()
        FileHandle.standardOutput.write(data)
        lock.unlock()
    }

    func log(_ message: String) {
        guard let data = (message + "\n").data(using: .utf8) else { return }
        FileHandle.standardError.write(data)
    }
}

private struct VisualSize {
    let width: CGFloat
    let totalHeight: CGFloat
    let contentHeight: CGFloat
}

private let collapsedExtraWidth: CGFloat = 24
private let collapsedLip: CGFloat = 8
/// Design tokens — a single source for the HUD's type scale, 4pt spacing
/// rhythm, corner radii, and the surface/text colors that sit on the flat
/// black pill. Every view stays on these values so the panel reads as one
/// deliberate system instead of ad-hoc sizes and opacities.
private enum T {
    // 4pt spacing rhythm
    static let space1: CGFloat = 4
    static let space2: CGFloat = 8
    static let space3: CGFloat = 12
    static let space4: CGFloat = 16
    static let pinnedHeaderOverlayTop: CGFloat = 10

    // corner radii
    static let rCard: CGFloat = 13
    static let rArt: CGFloat = 9

    // text ink on the black pill (a fixed opacity ladder, not SwiftUI's
    // theme-dependent .secondary/.tertiary which drift on a custom surface)
    static let ink = Color.white
    static let ink2 = Color.white.opacity(0.62)
    static let ink3 = Color.white.opacity(0.40)

    // card surface: a faint top-lit gradient + hairline reads as gentle
    // dimensionality on flat black — the premium-dark-UI look — without the
    // outer "silver border" that a stroke on the pill itself would create.
    static let cardTop = Color.white.opacity(0.08)
    static let cardBottom = Color.white.opacity(0.035)
    static let hairline = Color.white.opacity(0.08)
    static let control = Color.white.opacity(0.13)

    // type scale
    static let display = Font.system(size: 21, weight: .semibold, design: .rounded)
    static let title = Font.system(size: 13.5, weight: .semibold)
    static let body = Font.system(size: 12.5, weight: .medium)
    static let label = Font.system(size: 10.5, weight: .semibold)
    static let caption = Font.system(size: 10.5, weight: .medium)

    // one spring for every surface transition, so motion feels of a piece
    static let spring = Animation.spring(response: 0.4, dampingFraction: 0.82)
}

private func visualSize(for snapshot: HUDSnapshot, screen: NSScreen) -> VisualSize {
    let baseWidth = snapshot.baseWidth
    let baseHeight = snapshot.baseHeight
    let topInset = screen.safeAreaInsets.top

    if snapshot.visual == "idle_collapsed" {
        let leftWidth = screen.auxiliaryTopLeftArea?.width ?? 0
        let rightWidth = screen.auxiliaryTopRightArea?.width ?? 0
        let notchWidth = screen.frame.width - leftWidth - rightWidth
        if topInset > 0, notchWidth > 0 {
            let height = topInset + collapsedLip
            return VisualSize(
                width: notchWidth + collapsedExtraWidth,
                totalHeight: height,
                contentHeight: height
            )
        }
        return VisualSize(width: baseWidth, totalHeight: baseHeight, contentHeight: baseHeight)
    }

    return VisualSize(
        width: baseWidth,
        totalHeight: baseHeight,
        contentHeight: baseHeight
    )
}

private func rectNearlyEqual(_ lhs: NSRect, _ rhs: NSRect, tolerance: CGFloat = 0.5) -> Bool {
    abs(lhs.origin.x - rhs.origin.x) <= tolerance
        && abs(lhs.origin.y - rhs.origin.y) <= tolerance
        && abs(lhs.size.width - rhs.size.width) <= tolerance
        && abs(lhs.size.height - rhs.size.height) <= tolerance
}

private final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }
}

/// Bottom-only rounding for the collapsed pill, which fuses flush against
/// the physical notch/menu-bar edge above it.
private struct BottomRoundedRect: Shape {
    var radius: CGFloat

    func path(in rect: CGRect) -> Path {
        let r = min(radius, min(rect.width, rect.height) / 2)
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - r))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX - r, y: rect.maxY),
            control: CGPoint(x: rect.maxX, y: rect.maxY)
        )
        path.addLine(to: CGPoint(x: rect.minX + r, y: rect.maxY))
        path.addQuadCurve(
            to: CGPoint(x: rect.minX, y: rect.maxY - r),
            control: CGPoint(x: rect.minX, y: rect.maxY)
        )
        path.closeSubpath()
        return path
    }
}

/// Capsule (fully-rounded pill) button, matching NotchNook's "prefer round
/// buttons" style rather than macOS's default rounded-rectangle bezel.
private struct CapsuleButtonStyle: ButtonStyle {
    var prominent: Bool = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .semibold))
            .padding(.horizontal, 18)
            .padding(.vertical, 7)
            .background(
                Capsule(style: .continuous)
                    .fill(prominent ? AnyShapeStyle(Color.accentColor) : AnyShapeStyle(Color.white.opacity(0.13)))
                    .overlay {
                        if !prominent {
                            Capsule(style: .continuous)
                                .strokeBorder(Color.white.opacity(0.08), lineWidth: 0.75)
                        }
                    }
            )
            .foregroundStyle(prominent ? Color.white : Color.white.opacity(0.92))
            .scaleEffect(configuration.isPressed ? 0.93 : 1.0)
            .animation(.spring(response: 0.25, dampingFraction: 0.6), value: configuration.isPressed)
    }
}

/// SF Symbol per agent state — replaces emoji-in-string labels with crisp
/// vector glyphs that tint with the state's accent color.
private func stateSymbol(_ state: String) -> String {
    switch state {
    case "listening": return "waveform"
    case "processing": return "sparkles"
    case "executing": return "bolt.fill"
    case "success": return "checkmark.circle.fill"
    case "error": return "exclamationmark.circle.fill"
    case "danger_confirm": return "exclamationmark.triangle.fill"
    default: return "circle.fill"
    }
}

/// Borderless windows refuse key status by default; the notch text-input
/// field needs it to receive keystrokes.
private final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
}

/// Three tiny bars bouncing forever — the classic "audio playing" glyph.
/// A pink-to-cyan gradient (rather than a flat color) is what makes it read
/// as a lively music indicator instead of a generic loading spinner.
private struct EqualizerGlyph: View {
    @State private var up = false

    private var gradient: LinearGradient {
        LinearGradient(colors: [.pink, .purple, .cyan], startPoint: .bottom, endPoint: .top)
    }

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<3, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(gradient)
                    .frame(width: 2.5, height: up ? [10, 5, 8][i] : [4, 9, 5][i])
                    .animation(
                        .easeInOut(duration: 0.45).repeatForever(autoreverses: true).delay(Double(i) * 0.12),
                        value: up
                    )
            }
        }
        .frame(height: 10, alignment: .bottom)
        .onAppear { up = true }
    }
}

/// Notch text input for long text — voice dictation is unreliable past a few
/// words, so the user confirms/edits here with the keyboard.
private struct TextInputView: View {
    let prompt: String
    let emit: (String, [String: Any]) -> Void
    @State private var draft: String
    @FocusState private var focused: Bool

    init(prompt: String, prefill: String, emit: @escaping (String, [String: Any]) -> Void) {
        self.prompt = prompt
        self.emit = emit
        _draft = State(initialValue: prefill)
    }

    var body: some View {
        VStack(spacing: 8) {
            Text(prompt)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            TextField("입력할 내용", text: $draft)
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .onSubmit { emit("textSubmit", ["text": draft]) }
            HStack(spacing: 12) {
                Button("입력") { emit("textSubmit", ["text": draft]) }
                    .buttonStyle(CapsuleButtonStyle(prominent: true))
                    .keyboardShortcut(.defaultAction)
                Button("취소") { emit("textCancel", [:]) }
                    .buttonStyle(CapsuleButtonStyle())
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { focused = true } }
    }
}

private struct HUDView: View {
    let snapshot: HUDSnapshot
    let size: VisualSize
    let surfaceStartSize: CGSize?
    let surfaceContainerSize: CGSize?
    let surfaceAnimationID: Int
    let emit: (String, [String: Any]) -> Void

    @State private var surfaceScaleX: CGFloat = 1
    @State private var surfaceScaleY: CGFloat = 1

    private var accent: Color {
        Color(nsColor: snapshot.stateColor)
    }

    private var isCollapsed: Bool { snapshot.visual == "idle_collapsed" }

    private var cornerRadius: CGFloat {
        isCollapsed ? 10 : min(size.contentHeight / 2, 26)
    }

    /// Active states get a faint wash of their accent color bleeding up from
    /// the bottom of the pill — enough to read as "this state has a color"
    /// without competing with the (still legible) black glass surface.
    private var glowsWithAccent: Bool {
        ["listening", "success", "error", "danger_confirm"].contains(snapshot.state)
    }

    @ViewBuilder
    private var pillBackground: some View {
        // Solid black only — no light-colored bevel/highlight stroke. An
        // earlier version added a faint white gradient outline for a "glass"
        // look, but on a real notched display that read as a distracting
        // silver border rather than a bevel, so the pill is flat black now.
        //
        // EVERY visual — collapsed pill AND expanded panels — uses the same
        // bottom-only rounding: the top edge stays square and flush against
        // the notch/menu-bar so the shape reads as the Dynamic Island growing
        // straight down, never as a detached floating card.
        let shape = BottomRoundedRect(radius: cornerRadius)
        ZStack {
            // Fully opaque black: at 0.96 the anti-aliased rounded edge let the
            // background bleed ~4% through, which on a bright wallpaper read as a
            // faint grey rim. Solid black keeps the edge crisp with no halo.
            shape.fill(Color.black)
            if !isCollapsed && glowsWithAccent {
                shape.fill(
                    RadialGradient(
                        colors: [accent.opacity(0.22), .clear],
                        center: .bottom, startRadius: 0, endRadius: size.width * 0.6
                    )
                )
            }
        }
    }

    private var clipShape: AnyShape {
        // Square top, rounded bottom for all states — see pillBackground.
        AnyShape(BottomRoundedRect(radius: cornerRadius))
    }

    private var transitionAnchor: UnitPoint {
        // Hover expansion is the only visual that should read as opening out
        // from the notch's center. Other active panels stay top-attached so the
        // surface still feels fused to the menu-bar edge.
        snapshot.visual == "idle_peek" ? .center : .top
    }

    var body: some View {
        content
            .frame(width: size.width, height: size.contentHeight)
            .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: transitionAnchor)))
            .id(snapshot.visual)   // drives the transition on visual changes
        .frame(width: size.width, height: size.totalHeight)
        .foregroundStyle(.white)
        .background(pillBackground)
        .clipShape(clipShape)
        .overlay {
            if snapshot.visual == "danger_confirm" {
                clipShape.stroke(accent, lineWidth: 1.4)
            }
        }
        .overlay(alignment: .top) {
            if snapshot.visual == "idle_pinned" {
                pinnedHeader
                    .padding(.horizontal, T.space4)
                    .padding(.top, T.pinnedHeaderOverlayTop)
            }
        }
        // No shadow of any kind — neither a SwiftUI `.shadow()` nor the AppKit
        // window shadow (`hasShadow = false`). The window shadow used to supply
        // depth, but it drew a soft grey halo around the pill that read as a grey
        // border, so the surface is now a flat black shape with no outline.
        .contentShape(Rectangle())
        .onTapGesture {
            if snapshot.visual != "danger_confirm" && snapshot.visual != "text_input" {
                emit("click", [:])
            }
        }
        // Anchor the morph at the top-center — the notch's own edge. Scaling
        // about this point makes the panel open FROM THE TOP outward to the
        // left, right, and down all at once when growing, and draw straight
        // back up into the notch when shrinking — one motion run forward or
        // backward. The start scale is taken per-axis from the actual size
        // ratio (see notch_hud.py for each visual's dimensions), so the pill
        // opens along whatever proportion that surface calls for.
        .scaleEffect(x: surfaceScaleX, y: surfaceScaleY, anchor: .top)
        // While shrinking, render() holds the window at its old (larger) size so
        // the scaling-down pill isn't clipped; center the pill at the top of
        // that larger box so it retracts straight up toward the notch instead
        // of sticking to a side. When not shrinking the box equals the pill's
        // own size, so this is a no-op.
        .frame(
            width: surfaceContainerSize?.width ?? size.width,
            height: surfaceContainerSize?.height ?? size.totalHeight,
            alignment: .top
        )
        .onAppear {
            startSurfaceAnimationIfNeeded()
        }
        .onChange(of: surfaceAnimationID) {
            startSurfaceAnimationIfNeeded()
        }
        // During the collapsed→peek expansion the growth is carried entirely by
        // the explicit `surfaceScale` spring above. The window frame is snapped
        // to full size at once in render(), so the SwiftUI frame must snap too:
        // letting `.animation` also spring the frame here layered a second,
        // off-center resize on top of the scale — because NSHostingView pins the
        // still-narrow content to its leading edge, that resize read as the pill
        // unfurling to the RIGHT instead of growing straight out of the notch.
        // Suppress the implicit animation on that one render so only the
        // top-anchored scale plays.
        .animation(surfaceStartSize == nil ? T.spring : nil, value: snapshot.visual)
    }

    private func startSurfaceAnimationIfNeeded() {
        guard let start = surfaceStartSize else {
            surfaceScaleX = 1
            surfaceScaleY = 1
            return
        }
        // A start scale ABOVE 1 is allowed: a shrink plays this in reverse,
        // starting oversized (the larger surface) and settling to 1 (the small
        // target). The cap keeps a pathological ratio from exploding.
        let startX = max(0.05, min(8, start.width / max(1, size.width)))
        let startY = max(0.05, min(8, start.height / max(1, size.totalHeight)))
        var transaction = Transaction()
        transaction.disablesAnimations = true
        withTransaction(transaction) {
            surfaceScaleX = startX
            surfaceScaleY = startY
        }
        DispatchQueue.main.async {
            withAnimation(T.spring) {
                surfaceScaleX = 1
                surfaceScaleY = 1
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch snapshot.visual {
        case "idle_collapsed":
            Color.clear
        case "idle_peek":
            Text(snapshot.providerSummary)
                .font(T.body)
                .foregroundStyle(T.ink)
                .lineLimit(1)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case "idle_pinned":
            pinnedPanel
        case "listening":
            bars
        case "danger_confirm":
            danger
        case "text_input":
            TextInputView(prompt: snapshot.inputPrompt, prefill: snapshot.inputPrefill, emit: emit)
        default:
            stateLabel
        }
    }

    private var bars: some View {
        let bars = snapshot.micBars.isEmpty ? Array(repeating: CGFloat(0.08), count: 6) : snapshot.micBars
        return HStack(spacing: 8) {
            ForEach(Array(bars.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 3)
                    .fill(accent)
                    .frame(width: 6, height: max(3, value * max(1, size.contentHeight - 16)))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var stateLabel: some View {
        VStack(spacing: T.space1) {
            HStack(spacing: T.space2) {
                // Live activity indicator while the agent is working, so the
                // wait never looks frozen.
                if snapshot.state == "processing" || snapshot.state == "executing" {
                    ProgressView()
                        .controlSize(.small)
                        .tint(accent)
                } else {
                    Image(systemName: stateSymbol(snapshot.state))
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(accent)
                        .symbolRenderingMode(.hierarchical)
                }
                Text(snapshot.stateLabel)
                    .font(T.title)
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            if !snapshot.transcript.isEmpty {
                Text("\"\(snapshot.transcript)\"")
                    .font(T.caption)
                    .foregroundStyle(T.ink2)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, T.space4)
    }

    private var danger: some View {
        VStack(spacing: T.space2 + 2) {
            HStack(spacing: T.space1 + 2) {
                Image(systemName: stateSymbol("danger_confirm"))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(accent)
                Text(snapshot.stateLabel)
                    .font(T.title)
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            HStack(spacing: T.space3) {
                Button("실행") { emit("dangerAllow", [:]) }
                    .buttonStyle(CapsuleButtonStyle(prominent: true))
                    .tint(.red)
                    .keyboardShortcut(.defaultAction)
                Button("취소") { emit("dangerDeny", [:]) }
                    .buttonStyle(CapsuleButtonStyle())
                    .keyboardShortcut(.cancelAction)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 16)
    }

    private var artworkImage: NSImage? {
        guard !snapshot.mediaArtwork.isEmpty,
              let data = Data(base64Encoded: snapshot.mediaArtwork) else { return nil }
        return NSImage(data: data)
    }

    /// Small round transport button (prev/play-pause/next) — filled circle so
    /// it reads as tappable at this size, unlike a bare SF Symbol glyph.
    private func transportButton(_ symbol: String, _ event: String) -> some View {
        Button {
            emit(event, [:])
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.white)
                .frame(width: 27, height: 27)
                .background(Circle().fill(T.control))
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var mediaCardContent: some View {
        HStack(alignment: .center, spacing: 10) {
            Group {
                if let image = artworkImage {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: 40, height: 40)
                        .clipShape(RoundedRectangle(cornerRadius: T.rArt, style: .continuous))
                } else {
                    iconBadge("music.note", .pink, size: 40)
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(snapshot.mediaTitle)
                    .font(T.title)
                    .foregroundStyle(T.ink)
                    .lineLimit(1)
                Text(snapshot.mediaArtist)
                    .font(T.caption)
                    .foregroundStyle(T.ink2)
                    .lineLimit(1)
            }
            if snapshot.mediaPlaying {
                EqualizerGlyph()
            }
            Spacer(minLength: 4)
            if !snapshot.mediaPlayerApp.isEmpty {
                HStack(spacing: 6) {
                    transportButton("backward.fill", "mediaPrev")
                    transportButton(
                        snapshot.mediaPlaying ? "pause.fill" : "play.fill", "mediaPlayPause"
                    )
                    transportButton("forward.fill", "mediaNext")
                }
            }
        }
    }

    /// Faint card container that groups a widget. A subtle top-lit gradient
    /// plus a 1px hairline gives each segment gentle dimensionality on the
    /// flat-black pill — distinct-but-unified panel segments.
    private func card<Content: View>(
        fillHeight: Bool = false,
        @ViewBuilder _ content: () -> Content
    ) -> some View {
        content()
            .padding(.horizontal, T.space3)
            .padding(.vertical, T.space2 + 2)
            .frame(
                maxWidth: .infinity,
                maxHeight: fillHeight ? .infinity : nil,
                alignment: .leading
            )
            .background(
                RoundedRectangle(cornerRadius: T.rCard, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [T.cardTop, T.cardBottom],
                            startPoint: .top, endPoint: .bottom
                        )
                    )
            )
    }

    private func providerIcon(_ title: String) -> String {
        switch title {
        case "STT": return "waveform"
        case "LLM": return "cpu"
        case "TTS": return "speaker.wave.2"
        default: return "circle"
        }
    }

    /// A modern, monochrome app-icon-style badge: a squircle in the panel's
    /// own white-translucent material with a crisp white glyph. Kept identical
    /// across every widget (STT/LLM/TTS, clock, …) so the panel reads as one
    /// coherent system instead of a scatter of colors — the SF Symbol and
    /// label carry the difference.
    private func monoBadge(_ symbol: String, size: CGFloat = 24) -> some View {
        Image(systemName: symbol)
            .font(.system(size: size * 0.46, weight: .medium))
            .symbolRenderingMode(.monochrome)
            .foregroundStyle(T.ink)
            .frame(width: size, height: size)
            .background(
                RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
                    .fill(Color.white.opacity(0.10))
            )
            // Flatten glyph + background into one raster so they snap to the
            // pixel grid together. Without this, on a 1x (non-Retina) external
            // display the badge can land on a fractional layout origin, and the
            // glyph pixel-snaps ~1px away from its background box — the clock
            // then reads as sitting low inside its square. Invisible at 2x.
            .drawingGroup()
    }

    /// A small circular badge behind an SF Symbol — reads as a proper icon
    /// rather than a bare glyph, and the tinted background carries the
    /// per-widget color even before the eye reaches the label text.
    private func iconBadge(_ symbol: String, _ tint: Color, size: CGFloat = 26) -> some View {
        ZStack {
            Circle().fill(tint.opacity(0.18))
            Image(systemName: symbol)
                .font(.system(size: size * 0.44, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(tint)
        }
        .frame(width: size, height: size)
        // Same pixel-grid fix as monoBadge: keep the glyph centered against
        // its circle on 1x displays by rasterizing them as one unit.
        .drawingGroup()
    }

    private var pinnedPanel: some View {
        VStack(spacing: T.space2 + 2) {
            pinnedHeader
                .hidden()
                .accessibilityHidden(true)

            if snapshot.showClock || snapshot.showMedia {
                HStack(alignment: .center, spacing: T.space2 + 2) {
                    if snapshot.showMedia {
                        card { mediaCardContent }
                            .frame(maxWidth: .infinity)
                    }
                    if snapshot.showClock {
                        card {
                            HStack(alignment: .center, spacing: T.space2 + 2) {
                                monoBadge("clock", size: 26)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(snapshot.clockTime)
                                        .font(T.display)
                                        .foregroundStyle(T.ink)
                                        .monospacedDigit()
                                        .lineLimit(1)
                                    Text(snapshot.clockDate)
                                        .font(T.caption)
                                        .foregroundStyle(T.ink2)
                                        .lineLimit(1)
                                }
                            }
                        }
                        .frame(width: snapshot.showMedia ? nil : .infinity)
                    }
                }
            }

            HStack(spacing: T.space2 + 2) {
                ForEach(snapshot.providerColumns) { column in
                    card(fillHeight: true) {
                        HStack(alignment: .center, spacing: T.space2 + 2) {
                            monoBadge(providerIcon(column.title), size: 24)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(column.title)
                                    .font(T.label)
                                    .tracking(0.6)
                                    .foregroundStyle(T.ink)
                                ForEach(Array(column.lines.enumerated()), id: \.offset) { _, line in
                                    Text(line)
                                        .font(T.caption)
                                        .foregroundStyle(T.ink2)
                                        .lineLimit(1)
                                }
                            }
                        }
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)

            if !snapshot.routines.isEmpty {
                card {
                    VStack(alignment: .leading, spacing: T.space2 - 2) {
                        HStack(spacing: T.space1 + 1) {
                            Image(systemName: "bolt.fill")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.yellow)
                            Text("단축어")
                                .font(T.label)
                                .tracking(0.4)
                                .foregroundStyle(T.ink2)
                        }
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: T.space2) {
                                ForEach(snapshot.routines, id: \.self) { routine in
                                    routineChip(routine)
                                }
                            }
                        }
                    }
                }
            }

            HStack(spacing: T.space1) {
                Image(systemName: "chevron.up")
                    .font(.system(size: 8, weight: .bold))
                Text("다시 클릭하면 접힙니다")
                    .font(.system(size: 9.5, weight: .medium))
                    .tracking(0.3)
            }
            .foregroundStyle(T.ink3)
        }
        .padding(.horizontal, T.space4)
        .padding(.top, T.space3)
        .padding(.bottom, T.space2 + 2)
    }

    private var pinnedHeader: some View {
        HStack {
            HStack(spacing: T.space1 + 1) {
                Image(systemName: "mic.fill")
                    .font(.system(size: 11, weight: .semibold))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(T.ink)
                Text("VoiceDesk")
                    .font(T.label)
                    .tracking(0.4)
                    .foregroundStyle(T.ink2)
            }
            Spacer()
            if let pct = snapshot.batteryPercent {
                HStack(spacing: T.space1 - 1) {
                    Image(systemName: batterySymbol(pct))
                        .font(.system(size: 11))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(batteryColor(pct))
                    Text("\(pct)%")
                        .font(T.caption)
                        .foregroundStyle(T.ink2)
                        .monospacedDigit()
                }
            }
            // A SwiftUI Button's action does not fire while this panel's
            // window is non-key (only the text-input path makes it key), so
            // emit directly from a tap gesture like the rest of the HUD.
            Image(systemName: "gearshape.fill")
                .font(.system(size: 12))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(T.ink2)
                .contentShape(Rectangle())
                .highPriorityGesture(
                    TapGesture().onEnded { emit("openSettings", [:]) }
                )
        }
    }

    /// One saved routine as a tappable capsule chip in the quick-launch row.
    private func routineChip(_ name: String) -> some View {
        Button {
            emit("runRoutine", ["name": name])
        } label: {
            HStack(spacing: T.space1 + 1) {
                Image(systemName: "play.fill")
                    .font(.system(size: 8, weight: .semibold))
                Text(name)
                    .font(T.body)
                    .lineLimit(1)
            }
            .padding(.horizontal, T.space3)
            .padding(.vertical, T.space1 + 2)
            .background(Capsule(style: .continuous).fill(T.control))
        }
        .buttonStyle(.plain)
    }

    private func batteryColor(_ pct: Int) -> Color {
        snapshot.batteryCharging ? .green : (pct <= 20 ? .red : .secondary)
    }

    private func batterySymbol(_ pct: Int) -> String {
        if snapshot.batteryCharging { return "bolt.fill" }
        switch pct {
        case ..<15: return "battery.0"
        case ..<40: return "battery.25"
        case ..<65: return "battery.50"
        case ..<90: return "battery.75"
        default: return "battery.100"
        }
    }
}

private final class HUDController {
    private let emitter = EventEmitter()
    private var snapshot = HUDSnapshot()
    private var windows: [String: NSWindow] = [:]
    // Reusing the hosting view (instead of replacing contentView on every
    // render) is required for hover to work at all: recreating it tears down
    // and remounts the view's NSTrackingArea every call, which AppKit reports
    // as a fresh mouseExited/mouseEntered pair even though the pointer never
    // moved — observed as hoverEnter/hoverExit firing in an infinite ~40ms
    // loop that never survives long enough for the dwell timer to fire.
    private var hostingViews: [String: FirstMouseHostingView<HUDView>] = [:]
    private var lastVisual = ""
    private var lastState = ""
    // A second, independent source of the same oscillation: while the
    // window's frame is mid-animation (see the spring resize in render()),
    // AppKit's hit-testing for the hosting view's NSTrackingArea is
    // unreliable — it reports spurious mouseExited/mouseEntered pairs even
    // though the real cursor never moved. There is no way to distinguish
    // those from a genuine mouse-leave using the events alone, so hover
    // enter/exit is suppressed for the animation's duration after any frame
    // change; genuine clicks are never touched by this.
    private var suppressHoverUntil: Date = .distantPast
    private var lastHoverInside: Bool? = nil
    private var hoverMonitors: [Any] = []
    private let frameAnimationDuration: TimeInterval = 0.4
    private let hoverTopSlop: CGFloat = 12
    private let hoverSideSlop: CGFloat = 6
    private var surfaceAnimationID = 0

    /// Subtle NotchNook-style interaction sounds on meaningful transitions.
    private func playTransitionSound() {
        var name: String?
        if snapshot.visual == "idle_pinned" && lastVisual != "idle_pinned" {
            name = "Pop"
        } else if snapshot.state == "success" && lastState != "success" {
            name = "Glass"
        } else if snapshot.state == "error" && lastState != "error" {
            name = "Basso"
        } else if snapshot.state == "listening" && lastState != "listening" {
            name = "Tink"
        }
        if snapshot.interactionSounds, let name, let sound = NSSound(named: name) {
            sound.volume = 0.3
            sound.play()
        }
        lastVisual = snapshot.visual
        lastState = snapshot.state
    }

    func handle(_ line: String) {
        guard let data = line.data(using: .utf8),
              let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = raw["type"] as? String else {
            emitter.log("[SwiftHUD] invalid command")
            return
        }

        switch type {
        case "render":
            snapshot = HUDSnapshot(raw)
            render()
        case "hide":
            hide()
        case "quit":
            hide()
            NSApp.terminate(nil)
        default:
            emitter.log("[SwiftHUD] unknown command: \(type)")
        }
    }

    private func render() {
        guard snapshot.visible else {
            hide()
            return
        }
        installHoverMonitors()

        // A "surface morph" is any move along the idle size ladder
        // (collapsed → peek → pinned): a hover peek opening out of the notch, a
        // click growing the big pinned panel, and — in reverse — either of those
        // retracting back down. Growing and shrinking play the SAME top-anchored
        // scale, so the two read as one motion run forward or backward: always
        // swelling out of / drawing back into the notch, never resizing in from
        // a side.
        let surfaceExpands = isSurfaceExpansion(from: lastVisual, to: snapshot.visual)
        let surfaceShrinks = isSurfaceExpansion(from: snapshot.visual, to: lastVisual)
        if surfaceExpands || surfaceShrinks {
            surfaceAnimationID += 1
        }

        let activeKeys = Set(NSScreen.screens.map(screenKey))
        for key in windows.keys where !activeKeys.contains(key) {
            windows[key]?.orderOut(nil)
            windows.removeValue(forKey: key)
            hostingViews.removeValue(forKey: key)
        }

        for screen in NSScreen.screens {
            let key = screenKey(screen)
            let size = visualSize(for: snapshot, screen: screen)
            let frame = NSRect(
                x: screen.frame.midX - size.width / 2,
                y: screen.frame.maxY - size.totalHeight,
                width: size.width,
                height: size.totalHeight
            )
            let isNewWindow = windows[key] == nil
            let window = windows[key] ?? makeWindow(frame: frame)
            windows[key] = window
            let needsResize = !rectNearlyEqual(window.frame, frame)
            // Both directions scale between the surface on screen right now
            // (the window's current size) and the new one: a peek→pinned click
            // continues out of the peek panel, a pinned→peek retract draws back
            // into it. Capture it before the frame is touched. A brand-new
            // window has nothing to morph from, so it just appears.
            let surfaceStartSize: CGSize? =
                ((surfaceExpands || surfaceShrinks) && !isNewWindow && needsResize)
                ? window.frame.size : nil
            if needsResize {
                if surfaceExpands && surfaceStartSize != nil {
                    // Grow: jump to the bigger target now; the top-anchored
                    // scale carries the growth out of the notch.
                    suppressHoverUntil = Date().addingTimeInterval(frameAnimationDuration + 0.05)
                    window.setFrame(frame, display: true)
                    DispatchQueue.main.asyncAfter(deadline: .now() + frameAnimationDuration) { [weak self] in
                        self?.reconcileHover(force: true, confirmInside: true)
                    }
                } else if surfaceShrinks && surfaceStartSize != nil {
                    // Shrink: keep the window at its current (larger) size while
                    // the pill scales down inside it — a smaller window would
                    // clip the still-large pill and the retract would never be
                    // seen. Collapse the window to the small target only once the
                    // scale has settled, then re-render so the window (and its
                    // hover area) matches the pill exactly.
                    let settleDelay = frameAnimationDuration + 0.12
                    suppressHoverUntil = Date().addingTimeInterval(settleDelay + 0.05)
                    // If another render moves us to a different visual before the
                    // scale settles (e.g. a quick re-click or a state change),
                    // that render already owns the window — skip this now-stale
                    // collapse so it can't yank the window to the wrong size.
                    let settleVisual = snapshot.visual
                    let settleKey = key
                    DispatchQueue.main.asyncAfter(deadline: .now() + settleDelay) { [weak self, weak window] in
                        guard let self, let window, self.snapshot.visual == settleVisual else { return }
                        window.setFrame(frame, display: true)
                        self.settleShrunkSurface(key: settleKey)
                        self.reconcileHover(force: true, confirmInside: false)
                    }
                } else {
                    // A slight overshoot easing reads as a soft spring rather
                    // than AppKit's flat linear-ish default — the difference
                    // between a mechanical resize and a "grows out of the
                    // notch" feel.
                    suppressHoverUntil = Date().addingTimeInterval(frameAnimationDuration + 0.05)
                    NSAnimationContext.runAnimationGroup({ ctx in
                        ctx.duration = self.frameAnimationDuration
                        ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.32, 1.2, 0.4, 1.0)
                        window.animator().setFrame(frame, display: true)
                    }, completionHandler: { [weak self] in
                        self?.settleFrameAnimation(for: window)
                    })
                }
            }
            // During a shrink the window is briefly larger than the pill, so the
            // pill is centered at the window's top inside that box; otherwise the
            // box equals the pill and it's a no-op. Read AFTER the frame work
            // above so it reflects the grow-snap / shrink-hold.
            let surfaceContainerSize: CGSize? =
                surfaceStartSize != nil ? window.frame.size : nil
            installHUDView(
                forKey: key,
                into: window,
                size: size,
                surfaceStartSize: surfaceStartSize,
                surfaceContainerSize: surfaceContainerSize
            )
            if isNewWindow || !window.isVisible {
                window.orderFrontRegardless()
            }
        }

        // The text field must own keyboard focus while the input is open.
        if snapshot.visual == "text_input" {
            NSApp.activate(ignoringOtherApps: true)
            let mainKey = NSScreen.main.map(screenKey)
            if let key = mainKey, let window = windows[key] {
                window.makeKeyAndOrderFront(nil)
            } else {
                windows.values.first?.makeKeyAndOrderFront(nil)
            }
        }

        playTransitionSound()
    }

    /// Build the SwiftUI pill for one screen's window and mount it (reusing the
    /// existing hosting view so its NSTrackingArea survives — see the note on
    /// `hostingViews`). Shared by the main render loop and the per-window shrink
    /// settle so both mount identical views.
    private func installHUDView(
        forKey key: String,
        into window: NSWindow,
        size: VisualSize,
        surfaceStartSize: CGSize?,
        surfaceContainerSize: CGSize?
    ) {
        let hudView = HUDView(
            snapshot: snapshot,
            size: size,
            surfaceStartSize: surfaceStartSize,
            surfaceContainerSize: surfaceContainerSize,
            surfaceAnimationID: surfaceAnimationID,
            emit: makeEmitHandler()
        )
        if let hostingView = hostingViews[key] {
            hostingView.rootView = hudView
        } else {
            let hostingView = FirstMouseHostingView(rootView: hudView)
            hostingViews[key] = hostingView
            window.contentView = hostingView
        }
    }

    private func makeEmitHandler() -> (String, [String: Any]) -> Void {
        return { [weak self] event, extra in
            guard let self else { return }
            let isHoverEdge = (event == "hoverEnter" || event == "hoverExit")
            if isHoverEdge && Date() < self.suppressHoverUntil {
                return   // animation-artifact hover event — not a real cursor move
            }
            if event == "hoverEnter" {
                self.lastHoverInside = true
            } else if event == "hoverExit" {
                self.lastHoverInside = false
            }
            self.emitter.emit(event, extra)
        }
    }

    /// After a per-window shrink hold settles, drop the oversized container so
    /// the pill sits in its own (now small) frame. Rebuilds ONLY this window.
    ///
    /// It must NOT re-enter the global `render()`: on a multi-display setup each
    /// screen holds its own window and settles on its own delayed closure, so
    /// when the first screen's settle fires the sibling window on another screen
    /// is still mid-shrink. `render()` would re-loop over that sibling — but
    /// `lastVisual` has already advanced to the new visual, so the sibling no
    /// longer classifies as a shrink and falls through to the overshoot resize
    /// branch, springing that notch left-right. Touching one window avoids the
    /// cross-talk; each sibling settles cleanly on its own closure.
    private func settleShrunkSurface(key: String) {
        guard snapshot.visible,
              let window = windows[key],
              let screen = NSScreen.screens.first(where: { screenKey($0) == key }) else { return }
        let size = visualSize(for: snapshot, screen: screen)
        installHUDView(
            forKey: key,
            into: window,
            size: size,
            surfaceStartSize: nil,
            surfaceContainerSize: nil
        )
    }

    private func hide() {
        for window in windows.values {
            window.orderOut(nil)
        }
        removeHoverMonitors()
        lastHoverInside = nil
    }

    private func settleFrameAnimation(for window: NSWindow) {
        // Reconcile hover edges that may have been suppressed during the frame
        // animation. (The window has no shadow, so there is no shadow ghost to
        // re-derive here anymore.)
        reconcileHover(force: true, confirmInside: true)
    }

    /// Rank of an idle surface on the collapsed → peek → pinned size ladder,
    /// or nil for any non-idle visual (active states resize by their own
    /// window animation, not this scale-out).
    private func idleSurfaceRank(_ visual: String) -> Int? {
        switch visual {
        case "idle_collapsed": return 0
        case "idle_peek": return 1
        case "idle_pinned": return 2
        default: return nil
        }
    }

    /// True when `to` sits higher on that ladder than `from` — the surface is
    /// growing (notch→peek, peek→pinned, notch→pinned) and should play the
    /// top-anchored scale-out. Shrinking back down keeps the plain window
    /// resize.
    private func isSurfaceExpansion(from: String, to: String) -> Bool {
        guard let a = idleSurfaceRank(from), let b = idleSurfaceRank(to) else { return false }
        return a < b
    }

    private func installHoverMonitors() {
        guard hoverMonitors.isEmpty else { return }
        let mask: NSEvent.EventTypeMask = [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged]
        if let local = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { [weak self] event in
            self?.reconcileHover()
            return event
        }) {
            hoverMonitors.append(local)
        }
        if let global = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: { [weak self] _ in
            self?.reconcileHover()
        }) {
            hoverMonitors.append(global)
        }
    }

    private func removeHoverMonitors() {
        for monitor in hoverMonitors {
            NSEvent.removeMonitor(monitor)
        }
        hoverMonitors.removeAll()
    }

    private func reconcileHover(force: Bool = false, confirmInside: Bool = false) {
        guard snapshot.visible else { return }
        if !force && Date() < suppressHoverUntil {
            return
        }
        let cursor = NSEvent.mouseLocation
        let inside = windows.values.contains { window in
            window.isVisible && self.hoverFrame(for: window).contains(cursor)
        }
        guard lastHoverInside != inside else { return }
        lastHoverInside = inside
        if inside {
            emitter.emit(confirmInside ? "hoverConfirm" : "hoverEnter", [:])
        } else {
            emitter.emit("hoverExit", [:])
        }
    }

    private func hoverFrame(for window: NSWindow) -> NSRect {
        var frame = window.frame
        frame.origin.x -= hoverSideSlop
        frame.size.width += hoverSideSlop * 2
        frame.size.height += hoverTopSlop
        return frame
    }

    private func makeWindow(frame: NSRect) -> NSWindow {
        let window = KeyableWindow(
            contentRect: frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.statusWindow)) + 1)
        window.isOpaque = false
        window.backgroundColor = .clear
        // No window shadow: the non-opaque window's drop shadow rendered as a
        // soft grey halo hugging the pill's rounded edge, which read as a grey
        // border around the surface in every state. The pill is a flat black
        // shape with no outline of any kind.
        window.hasShadow = false
        window.ignoresMouseEvents = false
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .stationary,
            .ignoresCycle,
            .fullScreenAuxiliary,
        ]
        window.isReleasedWhenClosed = false
        return window
    }

    private func screenKey(_ screen: NSScreen) -> String {
        if let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
            return number.stringValue
        }
        return NSStringFromRect(screen.frame)
    }
}

private final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}

private let controller = HUDController()
private let app = NSApplication.shared
private let delegate = AppDelegate()
app.delegate = delegate

DispatchQueue.global(qos: .userInitiated).async {
    while let line = readLine(strippingNewline: true) {
        DispatchQueue.main.async {
            controller.handle(line)
        }
    }
    DispatchQueue.main.async {
        controller.handle("{\"type\":\"quit\"}")
    }
}

app.run()
withExtendedLifetime(delegate) {}
