import { useState, useEffect } from 'react'
import { api } from '../../../api/client'
import { useToastStore } from '../../../stores/toastStore'
import { 
  Save, AlertTriangle, Folder, FolderOpen, File, 
  Plus, Trash2, RefreshCw, FileCode
} from 'lucide-react'

interface Props { sandboxId: string }

interface FileNode {
  name: string
  type: 'file' | 'directory'
  size?: number
  children?: FileNode[]
}

export function WorkspaceTab({ sandboxId }: Props) {
  const toast = useToastStore(s => s.add)
  const [tree, setTree] = useState<FileNode | null>(null)
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({'/': true})
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [editorContent, setEditorContent] = useState('')
  const [originalContent, setOriginalContent] = useState('')
  const [loadingFile, setLoadingFile] = useState(false)
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [newFileName, setNewFileName] = useState('')
  const [showNewFileForm, setShowNewFileForm] = useState(false)

  // Load the full file tree
  const loadTree = async (silent = false) => {
    if (!silent) setRefreshing(true)
    setError('')
    try {
      const res = await api.listFiles(sandboxId)
      setTree(res as FileNode)
    } catch (e) {
      setError('Failed to load file explorer tree')
      toast('error', 'Failed to load file explorer')
    } finally {
      if (!silent) setRefreshing(false)
    }
  }

  useEffect(() => {
    loadTree()
  }, [sandboxId])

  // Toggle folder expansion
  const toggleFolder = (path: string) => {
    setExpandedFolders(prev => ({
      ...prev,
      [path]: !prev[path]
    }))
  }

  // Load file content when selected
  const selectFile = async (path: string) => {
    setLoadingFile(true)
    setError('')
    try {
      const res = await api.readFile(sandboxId, path)
      setSelectedFile(path)
      setEditorContent(res.content)
      setOriginalContent(res.content)
    } catch (e) {
      toast('error', `Failed to read file: ${path}`)
    } finally {
      setLoadingFile(false)
    }
  }

  // Save the currently open file
  const handleSave = async () => {
    if (!selectedFile) return
    setSaving(true)
    setError('')
    try {
      await api.writeFile(sandboxId, selectedFile, editorContent)
      setOriginalContent(editorContent)
      toast('success', 'File saved successfully')
      loadTree(true) // refresh tree silently
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to save'
      setError(msg)
      toast('error', msg)
    } finally {
      setSaving(false)
    }
  }

  // Create new file
  const handleCreateFile = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newFileName.trim()) return
    let path = newFileName.trim()
    if (!path.startsWith('/')) {
      path = '/' + path
    }
    try {
      await api.writeFile(sandboxId, path, '')
      setNewFileName('')
      setShowNewFileForm(false)
      toast('success', `File created: ${path}`)
      await loadTree(true)
      selectFile(path)
    } catch (e) {
      toast('error', 'Failed to create file')
    }
  }

  // Delete currently selected file
  const handleDelete = async () => {
    if (!selectedFile) return
    if (!window.confirm(`Are you sure you want to delete ${selectedFile}?`)) return
    try {
      await api.deleteFile(sandboxId, selectedFile)
      toast('success', 'File deleted')
      setSelectedFile(null)
      setEditorContent('')
      setOriginalContent('')
      loadTree(true)
    } catch (e) {
      toast('error', 'Failed to delete file')
    }
  }

  // Helper to generate line numbers for editor
  const lines = editorContent.split('\n')

  // Render tree node recursively
  const renderNode = (node: FileNode, currentPath: string = '') => {
    const nodePath = currentPath === '' ? '/' : `${currentPath}/${node.name}`
    const isFolder = node.type === 'directory'
    const isExpanded = expandedFolders[nodePath]
    const isSelected = selectedFile === nodePath

    if (node.name === '/' && currentPath === '') {
      // Root node
      return (
        <div key="root">
          <div 
            onClick={() => toggleFolder('/')}
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: 8, 
              padding: '6px 8px', 
              cursor: 'pointer',
              borderRadius: 4,
              color: 'var(--ink-deep)',
              fontWeight: 600,
              fontSize: 13
            }}
          >
            {isExpanded ? <FolderOpen size={16} color="var(--accent)" /> : <Folder size={16} color="var(--accent)" />}
            <span>workspace</span>
          </div>
          {isExpanded && node.children && (
            <div style={{ paddingLeft: 12 }}>
              {node.children.map(child => renderNode(child, ''))}
            </div>
          )}
        </div>
      )
    }

    return (
      <div key={nodePath} style={{ userSelect: 'none' }}>
        {isFolder ? (
          <div>
            <div 
              onClick={() => toggleFolder(nodePath)}
              style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: 8, 
                padding: '4px 8px', 
                cursor: 'pointer',
                borderRadius: 4,
                fontSize: 13,
                color: 'var(--ink)',
                transition: 'background 0.15s'
              }}
              className="tree-node-hover"
            >
              {isExpanded ? <FolderOpen size={14} color="var(--accent)" /> : <Folder size={14} color="var(--accent)" />}
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.name}</span>
            </div>
            {isExpanded && node.children && (
              <div style={{ paddingLeft: 12, borderLeft: '1px solid var(--hairline)', marginLeft: 6 }}>
                {node.children.map(child => renderNode(child, nodePath))}
              </div>
            )}
          </div>
        ) : (
          <div 
            onClick={() => selectFile(nodePath)}
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: 8, 
              padding: '4px 8px', 
              cursor: 'pointer',
              borderRadius: 4,
              fontSize: 13,
              background: isSelected ? 'var(--surface-card)' : 'transparent',
              color: isSelected ? 'var(--accent)' : 'var(--ink)',
              borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
              paddingLeft: isSelected ? 6 : 8,
              transition: 'all 0.15s'
            }}
            className="tree-node-hover"
          >
            <File size={14} color={isSelected ? 'var(--accent)' : 'var(--mute)'} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.name}</span>
          </div>
        )}
      </div>
    )
  }

  const isDirty = editorContent !== originalContent

  return (
    <div style={{ display: 'flex', height: '100%', borderTop: '1px solid var(--hairline)' }}>
      {/* File Explorer sidebar */}
      <div style={{ 
        width: 250, 
        borderRight: '1px solid var(--hairline)', 
        display: 'flex', 
        flexDirection: 'column',
        background: 'var(--surface-soft)',
        backdropFilter: 'blur(8px)',
        flexShrink: 0
      }}>
        {/* Controls */}
        <div style={{ 
          padding: '12px 16px', 
          borderBottom: '1px solid var(--hairline)', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between',
          gap: 6
        }}>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--mute)' }}>Explorer</span>
          <div style={{ display: 'flex', gap: 4 }}>
            <button onClick={() => setShowNewFileForm(!showNewFileForm)} className="btn-ghost" title="New file" style={{ width: 24, height: 24, padding: 0, justifyContent: 'center' }}>
              <Plus size={14} />
            </button>
            <button onClick={() => loadTree()} disabled={refreshing} className="btn-ghost" title="Refresh tree" style={{ width: 24, height: 24, padding: 0, justifyContent: 'center' }}>
              <RefreshCw size={14} className={refreshing ? 'spin-anim' : ''} />
            </button>
          </div>
        </div>

        {/* New File Form */}
        {showNewFileForm && (
          <form onSubmit={handleCreateFile} style={{ padding: '8px 12px', borderBottom: '1px solid var(--hairline)' }}>
            <input 
              className="input" 
              placeholder="/file.txt" 
              value={newFileName} 
              onChange={e => setNewFileName(e.target.value)} 
              style={{ height: 28, fontSize: 12, padding: '4px 8px', marginBottom: 6 }} 
              autoFocus 
            />
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button type="button" onClick={() => setShowNewFileForm(false)} className="btn-ghost" style={{ height: 20, padding: '0 6px', fontSize: 11 }}>Cancel</button>
              <button type="submit" className="btn-primary" style={{ height: 20, padding: '0 8px', fontSize: 11 }}>Create</button>
            </div>
          </form>
        )}

        {/* Tree Area */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 8px' }}>
          {tree ? renderNode(tree) : <div style={{ fontSize: 12, color: 'var(--ash)', padding: 8 }}>Loading file explorer...</div>}
        </div>
      </div>

      {/* Editor Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--surface-dark)' }}>
        {selectedFile ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            {/* Editor Header */}
            <div style={{ 
              height: 40, 
              borderBottom: '1px solid var(--hairline)', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'space-between', 
              padding: '0 16px',
              background: 'var(--surface-dark-elevated)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--mute)', fontFamily: 'monospace' }}>
                <FileCode size={14} color="var(--accent)" />
                <span style={{ color: 'var(--ink)' }}>{selectedFile}</span>
                {isDirty && <span style={{ color: 'var(--warning)', fontSize: 10 }}>● modified</span>}
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button 
                  onClick={handleDelete} 
                  className="btn-danger" 
                  style={{ height: 26, fontSize: 11, padding: '0 8px', gap: 4 }}
                  title="Delete file"
                >
                  <Trash2 size={12} /> Delete
                </button>
                <button 
                  onClick={handleSave} 
                  disabled={saving || !isDirty} 
                  className="btn-primary" 
                  style={{ 
                    height: 26, 
                    fontSize: 11, 
                    padding: '0 10px', 
                    gap: 4,
                    opacity: isDirty ? 1 : 0.5,
                    cursor: isDirty ? 'pointer' : 'default'
                  }}
                >
                  <Save size={12} /> {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>

            {/* Error banner */}
            {error && (
              <div role="alert" style={{ 
                background: 'rgba(239, 68, 68, 0.1)', 
                borderBottom: '1px solid var(--danger)', 
                padding: '8px 16px', 
                color: 'var(--danger)', 
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}>
                <AlertTriangle size={14} />
                <span>{error}</span>
              </div>
            )}

            {/* Editor Canvas */}
            {loadingFile ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--mute)', fontSize: 13 }}>
                <RefreshCw size={20} className="spin-anim" style={{ marginRight: 8 }} /> Loading file contents...
              </div>
            ) : (
              <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
                {/* Custom Line Numbers Column */}
                <div style={{ 
                  width: 48, 
                  background: 'rgba(2, 6, 23, 0.3)', 
                  borderRight: '1px solid var(--hairline)', 
                  padding: '12px 0', 
                  display: 'flex', 
                  flexDirection: 'column', 
                  alignItems: 'flex-end', 
                  userSelect: 'none',
                  fontSize: 11,
                  fontFamily: 'var(--mono)',
                  color: 'var(--ash)',
                  lineHeight: '1.6',
                  paddingRight: 8,
                  boxSizing: 'border-box'
                }}>
                  {lines.map((_, idx) => (
                    <div key={idx} style={{ height: '1.6em' }}>{idx + 1}</div>
                  ))}
                </div>

                {/* Editor Textarea */}
                <textarea
                  value={editorContent}
                  onChange={e => setEditorContent(e.target.value)}
                  style={{ 
                    flex: 1, 
                    height: '100%', 
                    background: 'transparent', 
                    border: 'none', 
                    outline: 'none', 
                    color: '#e2e8f0', 
                    fontFamily: 'var(--mono)', 
                    fontSize: 12, 
                    lineHeight: '1.6', 
                    padding: '12px',
                    resize: 'none',
                    whiteSpace: 'pre',
                    overflowX: 'auto',
                    boxSizing: 'border-box'
                  }}
                  placeholder="File content..."
                  aria-label="File content editor"
                />
              </div>
            )}
          </div>
        ) : (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--mute)' }}>
            <FileCode size={36} strokeWidth={1} style={{ marginBottom: 12, color: 'var(--ash)' }} />
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--ink)' }}>No File Selected</div>
            <div style={{ fontSize: 12, color: 'var(--ash)', marginTop: 4 }}>Select a file from the explorer sidebar to begin editing</div>
          </div>
        )}
      </div>
    </div>
  )
}
