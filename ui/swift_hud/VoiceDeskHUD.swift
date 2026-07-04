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
    /// Gap between the screen top and the pill's top edge — 0 for the
    /// notch-hugging collapsed pill, a few points for every expanded state
    /// (reference: NotchNook's panel floats just clear of the menu bar
    /// rather than fusing flush with it).
    let topGap: CGFloat
}

private let collapsedExtraWidth: CGFloat = 24
private let collapsedLip: CGFloat = 8
private let expandedTopGap: CGFloat = 6

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
                contentHeight: height,
                topGap: 0
            )
        }
        return VisualSize(width: baseWidth, totalHeight: baseHeight, contentHeight: baseHeight, topGap: 0)
    }

    return VisualSize(
        width: baseWidth,
        totalHeight: topInset + expandedTopGap + baseHeight,
        contentHeight: baseHeight,
        topGap: topInset + expandedTopGap
    )
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
                    .fill(prominent ? Color.accentColor : Color.white.opacity(0.14))
            )
            .foregroundStyle(prominent ? .white : .primary)
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
    let emit: (String, [String: Any]) -> Void

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
        if isCollapsed {
            BottomRoundedRect(radius: cornerRadius).fill(Color.black.opacity(0.96))
        } else {
            let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            ZStack {
                shape.fill(Color.black.opacity(0.96))
                if glowsWithAccent {
                    shape.fill(
                        RadialGradient(
                            colors: [accent.opacity(0.22), .clear],
                            center: .bottom, startRadius: 0, endRadius: size.width * 0.6
                        )
                    )
                }
            }
        }
    }

    private var clipShape: AnyShape {
        isCollapsed
            ? AnyShape(BottomRoundedRect(radius: cornerRadius))
            : AnyShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
    }

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: max(0, size.totalHeight - size.contentHeight))
            content
                .frame(width: size.width, height: size.contentHeight)
                .transition(.opacity.combined(with: .scale(scale: 0.97, anchor: .top)))
                .id(snapshot.visual)   // drives the transition on visual changes
        }
        .frame(width: size.width, height: size.totalHeight)
        .foregroundStyle(.white)
        .background(pillBackground)
        .clipShape(clipShape)
        .overlay {
            if snapshot.visual == "danger_confirm" {
                clipShape.stroke(accent, lineWidth: 1.4)
            }
        }
        .shadow(color: .black.opacity(isCollapsed ? 0 : 0.35), radius: 18, y: 8)
        .contentShape(Rectangle())
        .onHover { inside in
            emit(inside ? "hoverEnter" : "hoverExit", [:])
        }
        .onTapGesture {
            if snapshot.visual != "danger_confirm" && snapshot.visual != "text_input" {
                emit("click", [:])
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.82), value: snapshot.visual)
    }

    @ViewBuilder
    private var content: some View {
        switch snapshot.visual {
        case "idle_collapsed":
            Color.clear
        case "idle_peek":
            Text(snapshot.providerSummary)
                .font(.system(size: 12.5, weight: .medium))
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
        VStack(spacing: 4) {
            HStack(spacing: 8) {
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
                    .font(.system(size: 13.5, weight: .medium))
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            if !snapshot.transcript.isEmpty {
                Text("\"\(snapshot.transcript)\"")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 14)
    }

    private var danger: some View {
        VStack(spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: stateSymbol("danger_confirm"))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(accent)
                Text(snapshot.stateLabel)
                    .font(.system(size: 13.5, weight: .medium))
                    .foregroundStyle(accent)
                    .lineLimit(1)
            }
            HStack(spacing: 12) {
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
                .frame(width: 26, height: 26)
                .background(Circle().fill(Color.white.opacity(0.14)))
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
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                } else {
                    iconBadge("music.note", .pink, size: 40)
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(snapshot.mediaTitle)
                    .font(.system(size: 12.5, weight: .semibold))
                    .lineLimit(1)
                Text(snapshot.mediaArtist)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
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

    /// Faint card container that groups a widget, echoing NotchNook's
    /// distinct-but-unified panel segments.
    private func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        content()
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Color.white.opacity(0.055))
            )
    }

    private func providerIcon(_ title: String) -> String {
        switch title {
        case "STT": return "waveform"
        case "LLM": return "cpu"
        case "TTS": return "speaker.wave.2.fill"
        default: return "circle.fill"
        }
    }

    private func providerColor(_ title: String) -> Color {
        switch title {
        case "STT": return Color(red: 0.2, green: 0.8, blue: 1.0)
        case "LLM": return Color(red: 0.6, green: 0.5, blue: 1.0)
        case "TTS": return Color(red: 0.2, green: 0.9, blue: 0.5)
        default: return .secondary
        }
    }

    /// A small circular badge behind an SF Symbol — reads as a proper icon
    /// rather than a bare glyph, and the tinted background carries the
    /// per-widget color even before the eye reaches the label text.
    private func iconBadge(_ symbol: String, _ tint: Color, size: CGFloat = 26) -> some View {
        ZStack {
            Circle().fill(tint.opacity(0.16))
            Image(systemName: symbol)
                .font(.system(size: size * 0.44, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(tint)
        }
        .frame(width: size, height: size)
    }

    private var pinnedPanel: some View {
        VStack(spacing: 10) {
            HStack {
                HStack(spacing: 5) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 11, weight: .semibold))
                        .symbolRenderingMode(.multicolor)
                    Text("VoiceDesk")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let pct = snapshot.batteryPercent {
                    HStack(spacing: 3) {
                        Image(systemName: batterySymbol(pct))
                            .font(.system(size: 11))
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(batteryColor(pct))
                        Text("\(pct)%")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                }
                Button {
                    emit("openSettings", [:])
                } label: {
                    Image(systemName: "gearshape.fill")
                        .font(.system(size: 12))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }

            if snapshot.showClock || snapshot.showMedia {
                HStack(alignment: .center, spacing: 10) {
                    if snapshot.showMedia {
                        card { mediaCardContent }
                            .frame(maxWidth: .infinity)
                    }
                    if snapshot.showClock {
                        card {
                            HStack(alignment: .center, spacing: 10) {
                                iconBadge("clock.fill", .orange)
                                VStack(alignment: .leading, spacing: 0) {
                                    Text(snapshot.clockTime)
                                        .font(.system(size: 20, weight: .semibold))
                                        .monospacedDigit()
                                        .lineLimit(1)
                                    Text(snapshot.clockDate)
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                        }
                        .frame(width: snapshot.showMedia ? nil : .infinity)
                    }
                }
            }

            HStack(spacing: 10) {
                ForEach(snapshot.providerColumns) { column in
                    card {
                        HStack(alignment: .center, spacing: 10) {
                            iconBadge(providerIcon(column.title), providerColor(column.title), size: 24)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(column.title)
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(providerColor(column.title))
                                ForEach(Array(column.lines.enumerated()), id: \.offset) { _, line in
                                    Text(line)
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                        }
                    }
                }
            }

            if !snapshot.routines.isEmpty {
                card {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 5) {
                            Image(systemName: "bolt.fill")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.yellow)
                            Text("단축어")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(snapshot.routines, id: \.self) { routine in
                                    routineChip(routine)
                                }
                            }
                        }
                    }
                }
            }

            HStack(spacing: 4) {
                Image(systemName: "chevron.up")
                    .font(.system(size: 8, weight: .bold))
                Text("다시 클릭하면 접힙니다")
                    .font(.system(size: 9.5))
            }
            .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 14)
        .padding(.top, 12)
        .padding(.bottom, 10)
    }

    /// One saved routine as a tappable capsule chip in the quick-launch row.
    private func routineChip(_ name: String) -> some View {
        Button {
            emit("runRoutine", ["name": name])
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "play.fill")
                    .font(.system(size: 8, weight: .semibold))
                Text(name)
                    .font(.system(size: 11, weight: .medium))
                    .lineLimit(1)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Capsule(style: .continuous).fill(Color.white.opacity(0.1)))
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
    private let frameAnimationDuration: TimeInterval = 0.4

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
            let window = windows[key] ?? makeWindow(frame: frame)
            windows[key] = window
            if window.frame != frame {
                suppressHoverUntil = Date().addingTimeInterval(frameAnimationDuration + 0.05)
                // A slight overshoot easing reads as a soft spring rather
                // than AppKit's flat linear-ish default — the difference
                // between a mechanical resize and a "grows out of the
                // notch" feel.
                NSAnimationContext.runAnimationGroup { ctx in
                    ctx.duration = self.frameAnimationDuration
                    ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.32, 1.2, 0.4, 1.0)
                    window.animator().setFrame(frame, display: true)
                }
            }
            let hudView = HUDView(snapshot: snapshot, size: size) { [weak self] event, extra in
                guard let self else { return }
                let isHoverEdge = (event == "hoverEnter" || event == "hoverExit")
                if isHoverEdge && Date() < self.suppressHoverUntil {
                    return   // animation-artifact hover event — not a real cursor move
                }
                self.emitter.emit(event, extra)
            }
            if let hostingView = hostingViews[key] {
                hostingView.rootView = hudView
            } else {
                let hostingView = FirstMouseHostingView(rootView: hudView)
                hostingViews[key] = hostingView
                window.contentView = hostingView
            }
            window.orderFrontRegardless()
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

    private func hide() {
        for window in windows.values {
            window.orderOut(nil)
        }
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
        window.hasShadow = true
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
