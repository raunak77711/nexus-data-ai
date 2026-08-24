import { useEffect, useMemo, useState } from 'react'
import Plotly from 'plotly.js/lib/core'
import bar from 'plotly.js/lib/bar'
import box from 'plotly.js/lib/box'
import heatmap from 'plotly.js/lib/heatmap'
import histogram from 'plotly.js/lib/histogram'
import scatter from 'plotly.js/lib/scatter'
import scattermap from 'plotly.js/lib/scattermap'
import createPlotlyComponent from 'react-plotly.js/factory'
import './PlotFigure.css'

/**
 * A hand-assembled plotly bundle rather than the default `react-plotly.js`
 * import.
 *
 * The default entry point pulls in every trace type plotly ships -- 3D, WebGL,
 * finance, polar, ternary, sankey -- which is a ~4.9MB JavaScript payload for
 * an app that draws five kinds of chart. Registering only the five keeps the
 * bundle to roughly a third of that.
 *
 * The list is not arbitrary; it is exactly what core/ can emit:
 *   scatter    -- the timeseries line and its rolling overlay, and the forecast
 *   bar        -- the tabular world's mean-by-category chart, and rankings
 *   box        -- a spec chart comparing a measure across categories
 *   histogram  -- the tabular world's distribution
 *   heatmap    -- the correlation matrix
 *   scattermap -- the geo world (MapLibre; core/ deliberately avoids the
 *                 deprecated mapbox trace family, so scattermapbox is NOT here)
 *
 * If a world ever gains a sixth chart type, plotly will report "trace type not
 * found" rather than failing silently -- which is the right failure, and the
 * fix is one line here.
 */
Plotly.register([scatter, bar, box, histogram, heatmap, scattermap])
const Plot = createPlotlyComponent(Plotly)

/**
 * One plotly figure, decoded from the JSON string the API sends.
 *
 * The server returns `figures_json` as `{ name: "<json string>" }`. That is
 * parsed here and nowhere else, so a malformed payload produces one contained
 * error message instead of a blank white area with a console exception behind it.
 *
 * WHY the layout is merged rather than used as-is: the figure arrives with
 * plotly's default template, which is a white card with grey gridlines and
 * Arial. Dropped into this page it would look like a screenshot of a different
 * application. The overrides below make the chart transparent to the page's own
 * surface and switch it to the app's typeface -- but they touch presentation
 * only. No override changes an axis range, a trace's data, a colour SCALE, or
 * anything else that could alter what the chart says.
 *
 * SERIES COLOUR is the one addition to that list, and it is worth being precise
 * about. plotly express assigns each category in a split chart a colour from its
 * own rainbow sequence, which is baked into the figure by the server. The server
 * cannot know whether the person looking at it has a light or a dark page, and a
 * fixed sequence that is legible on both would have to live in the middle of the
 * range, where the steps are too close together to tell apart.
 *
 * So recolourSeries() below reassigns those colours from the page's own ramp, in
 * trace order. What it does NOT touch: any trace whose colour is an ARRAY or a
 * colour scale, because there the colour is the data -- the correlation heatmap
 * and the map both encode a value in their colour, and repainting either would
 * be changing what the chart says rather than how it looks. The legend still
 * maps each name to the colour drawn for it, so nothing about reading the chart
 * changes; only the palette does.
 */

/** Plotly's toolbar, trimmed to what is actually useful for these charts. */
const CONFIG = {
  displaylogo: false,
  responsive: true,
  // Kept: zoom, pan, reset, download. Removed: lasso/box select (they select
  // nothing here, since nothing downstream consumes a selection) and the
  // autoscale/spike toggles, which mostly confuse.
  modeBarButtonsToRemove: [
    'select2d', 'lasso2d', 'toggleSpikelines',
    'hoverClosestCartesian', 'hoverCompareCartesian',
  ],
  toImageButtonOptions: { format: 'png', scale: 2 },
}

/**
 * Read the live theme off the document.
 *
 * The palette is defined in CSS custom properties, so the chart asks the
 * cascade what colour text is rather than keeping a duplicate JavaScript copy
 * that would drift the first time a token changed.
 */
function readTheme() {
  const styles = getComputedStyle(document.documentElement)
  const value = (name, fallback) => styles.getPropertyValue(name).trim() || fallback
  return {
    fg: value('--fg', '#0b0b0d'),
    muted: value('--fg-muted', '#55555f'),
    grid: value('--border', '#ebebee'),
    surface: value('--bg-elevated', '#ffffff'),
    font: value('--font-body', 'Inter, sans-serif'),
    // The series ramp, read from the cascade rather than duplicated here so a
    // repalette is a change to tokens.css alone. See the note beside
    // --chart-1 for the CVD-safety reasoning behind the fixed hue order.
    colorway: [
      value('--chart-1', '#2a78d6'),
      value('--chart-2', '#eb6834'),
      value('--chart-3', '#1baf7a'),
      value('--chart-4', '#eda100'),
      value('--chart-5', '#e87ba4'),
      value('--chart-6', '#008300'),
    ],
  }
}

/**
 * @param {object}  props
 * @param {string} [props.figureJson] a `fig.to_json()` string from the API
 * @param {object} [props.figure]     an already-built `{data, layout}` object,
 *   used by the forecast panel, whose chart is composed in the browser from
 *   record arrays rather than sent as a server-rendered figure. Both paths land
 *   in the same theming and config code below, so the two kinds of chart cannot
 *   drift apart visually.
 */
export default function PlotFigure({ figureJson, figure: figureProp, title, height }) {
  const [theme, setTheme] = useState(readTheme)

  // Re-read the tokens when the OS theme flips, so an open chart recolours with
  // the rest of the page instead of staying in the previous scheme.
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setTheme(readTheme())
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const parsed = useMemo(() => {
    if (figureProp) return { figure: figureProp }
    try {
      const figure = JSON.parse(figureJson)
      if (!figure || typeof figure !== 'object' || !Array.isArray(figure.data)) {
        return { error: 'The server sent a figure in an unexpected shape.' }
      }
      return { figure }
    } catch {
      return { error: 'The figure could not be decoded.' }
    }
  }, [figureJson, figureProp])

  if (parsed.error) {
    return (
      <p className="status-note" data-tone="error">
        {parsed.error}
      </p>
    )
  }

  const { layout } = parsed.figure
  const data = recolourSeries(parsed.figure.data, theme.colorway)

  const merged = {
    ...layout,
    autosize: true,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    colorway: layout?.colorway ?? theme.colorway,
    font: { family: theme.font, size: 12, color: theme.muted },
    // The figure carries its own title from the server; it is suppressed here
    // because the panel already has a real <h3> above it, and two titles of
    // different type styles saying the same thing looks like an accident.
    title: undefined,
    margin: { l: 56, r: 20, t: 12, b: 44, ...(layout?.margin ?? {}) },
    hoverlabel: {
      bgcolor: theme.surface,
      bordercolor: theme.grid,
      font: { family: theme.font, size: 12, color: theme.fg },
      ...(layout?.hoverlabel ?? {}),
    },
    legend: {
      orientation: 'h',
      y: -0.18,
      x: 0,
      font: { size: 11 },
      ...(layout?.legend ?? {}),
    },
    xaxis: { gridcolor: theme.grid, zerolinecolor: theme.grid, ...(layout?.xaxis ?? {}) },
    yaxis: { gridcolor: theme.grid, zerolinecolor: theme.grid, ...(layout?.yaxis ?? {}) },
  }

  // A map figure has no cartesian axes and a zero margin of its own; leaving the
  // axis overrides in place is harmless, but restoring its margin is not.
  if (layout?.map || layout?.mapbox) {
    merged.margin = { l: 0, r: 0, t: 0, b: 0 }
  }

  return (
    <div className="plot-figure" style={height ? { height } : undefined}>
      <Plot
        data={data}
        layout={merged}
        config={CONFIG}
        useResizeHandler
        style={{ width: '100%', height: '100%' }}
        aria-label={title}
      />
    </div>
  )
}


/**
 * Repaint categorical series from the page's ramp, leaving data colours alone.
 *
 * A trace is a "series" when its colour is one flat colour standing for its
 * name. A trace whose colour is an array, or which carries a colour scale, is
 * encoding a value per point -- that is data, and it is returned untouched.
 */
function recolourSeries(traces, colorway) {
  if (!Array.isArray(traces) || !colorway?.length) return traces

  let seriesIndex = 0
  return traces.map((trace) => {
    const marker = trace.marker ?? {}
    const encodesValue =
      Array.isArray(marker.color) ||
      marker.colorscale !== undefined ||
      marker.colorbar !== undefined ||
      trace.colorscale !== undefined ||
      ['heatmap', 'histogram2d', 'choropleth', 'contour'].includes(trace.type)

    if (encodesValue) return trace

    const colour = colorway[seriesIndex % colorway.length]
    seriesIndex += 1

    const next = { ...trace }
    if (trace.line && typeof trace.line === 'object') {
      next.line = { ...trace.line, color: colour }
    }
    if (trace.marker && typeof trace.marker === 'object') {
      next.marker = { ...trace.marker, color: colour }
    }
    // A bar or histogram with no explicit marker still needs one to be told
    // what colour to be; without this it falls back to plotly's default blue.
    if (!next.marker && ['bar', 'histogram', 'box'].includes(trace.type)) {
      next.marker = { color: colour }
    }
    return next
  })
}
