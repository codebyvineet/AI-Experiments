import { useState, useEffect } from 'react';
import { api } from '../api';

export default function ItemsPanel({ token, user }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState({ name: '', description: '', data: '' });

  const loadItems = async () => {
    setLoading(true);
    try {
      const data = await api.listItems(token);
      setItems(data.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadItems();
  }, [token]);

  const handleCreate = async () => {
    try {
      let parsedData = {};
      if (formData.data && formData.data.trim()) {
        try {
          parsedData = JSON.parse(formData.data);
        } catch (e) {
          alert('Invalid JSON in Data field. Use format like: {"key": "value"}');
          return;
        }
      }
      const item = {
        name: formData.name,
        description: formData.description,
        data: parsedData
      };
      await api.createItem(token, item);
      setShowForm(false);
      setFormData({ name: '', description: '', data: '' });
      loadItems();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleUpdate = async () => {
    if (!editingItem) return;
    try {
      let parsedData = {};
      if (formData.data && formData.data.trim()) {
        try {
          parsedData = JSON.parse(formData.data);
        } catch (e) {
          alert('Invalid JSON in Data field. Use format like: {"key": "value"}');
          return;
        }
      }
      const item = {
        name: formData.name,
        description: formData.description,
        data: parsedData
      };
      await api.updateItem(token, editingItem.id, item);
      setEditingItem(null);
      setFormData({ name: '', description: '', data: '' });
      loadItems();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleDelete = async (itemId) => {
    if (!confirm('Are you sure you want to delete this item?')) return;
    try {
      await api.deleteItem(token, itemId);
      loadItems();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const startEdit = (item) => {
    setEditingItem(item);
    setFormData({
      name: item.name,
      description: item.description || '',
      data: item.data ? JSON.stringify(item.data, null, 2) : ''
    });
    setShowForm(false);
  };

  const canWrite = ['admin', 'user'].includes(user.role);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold">📦 Items Management</h2>
          <p className="text-gray-400 text-sm">CRUD operations via REST API</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadItems}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded font-medium transition-colors"
          >
            🔄 Refresh
          </button>
          {canWrite && (
            <button
              onClick={() => {
                setShowForm(!showForm);
                setEditingItem(null);
                setFormData({ name: '', description: '', data: '' });
              }}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded font-medium transition-colors"
            >
              ➕ New Item
            </button>
          )}
        </div>
      </div>

      {/* Form */}
      {(showForm || editingItem) && canWrite && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="font-medium mb-4">
            {editingItem ? '✏️ Edit Item' : '➕ Create New Item'}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-300 mb-1">Name *</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Description</label>
              <input
                type="text"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm text-gray-300 mb-1">Data (JSON)</label>
              <textarea
                value={formData.data}
                onChange={(e) => setFormData({ ...formData, data: e.target.value })}
                placeholder='{"key": "value"}'
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded h-24 font-mono text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={editingItem ? handleUpdate : handleCreate}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded font-medium transition-colors"
            >
              {editingItem ? '💾 Update' : '✅ Create'}
            </button>
            <button
              onClick={() => {
                setShowForm(false);
                setEditingItem(null);
                setFormData({ name: '', description: '', data: '' });
              }}
              className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded font-medium transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Items List */}
      <div className="bg-gray-800 rounded-lg border border-gray-700">
        <div className="p-4 border-b border-gray-700">
          <h3 className="font-medium">📋 Items ({items.length})</h3>
        </div>
        
        {loading ? (
          <div className="p-8 text-center text-gray-400">Loading...</div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-gray-400">
            No items found. Create one to get started!
          </div>
        ) : (
          <div className="divide-y divide-gray-700">
            {items.map((item) => (
              <div key={item.id} className="p-4 hover:bg-gray-700/30 transition-colors">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <h4 className="font-medium text-blue-400">{item.name}</h4>
                    <p className="text-sm text-gray-400 mt-1">{item.description || 'No description'}</p>
                    <p className="text-xs text-gray-500 mt-1">ID: {item.id}</p>
                    {item.data && Object.keys(item.data).length > 0 && (
                      <div className="mt-2 p-2 bg-gray-700/50 rounded text-xs font-mono">
                        {JSON.stringify(item.data, null, 2)}
                      </div>
                    )}
                  </div>
                  {canWrite && (
                    <div className="flex gap-2 ml-4">
                      <button
                        onClick={() => startEdit(item)}
                        className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm transition-colors"
                      >
                        ✏️ Edit
                      </button>
                      <button
                        onClick={() => handleDelete(item.id)}
                        className="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-sm transition-colors"
                      >
                        🗑️ Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Info */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="font-medium mb-2">ℹ️ API Endpoints Used</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
          <code className="bg-gray-700 p-2 rounded">GET /items</code>
          <code className="bg-gray-700 p-2 rounded">POST /items</code>
          <code className="bg-gray-700 p-2 rounded">PUT /items/:id</code>
          <code className="bg-gray-700 p-2 rounded">DELETE /items/:id</code>
        </div>
      </div>
    </div>
  );
}
