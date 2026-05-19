package ui

import (
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/Agent-Field/agentfield/control-plane/internal/logger"
	"github.com/Agent-Field/agentfield/control-plane/internal/storage"
	"github.com/gin-gonic/gin"
)

type UploadProxyHandler struct {
	Storage storage.StorageProvider
}

func (h *UploadProxyHandler) ProxyUploadHandler(c *gin.Context) {
	agentID := c.Param("agentId")
	if agentID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "agentId is required"})
		return
	}

	agent, err := h.Storage.GetAgent(c.Request.Context(), agentID)
	if err != nil || agent == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "agent not found"})
		return
	}

	base := strings.TrimSpace(agent.BaseURL)
	if base == "" {
		c.JSON(http.StatusBadGateway, gin.H{"error": "agent_unreachable", "message": "agent has no base_url"})
		return
	}

	upstream := strings.TrimSuffix(base, "/") + "/upload"

	client := &http.Client{Timeout: 60 * time.Second}
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, upstream, c.Request.Body)
	if err != nil {
		logger.Logger.Error().Err(err).Str("agent", agentID).Msg("failed to create upload proxy request")
		c.JSON(http.StatusInternalServerError, gin.H{"error": "proxy_request_failed"})
		return
	}
	req.Header.Set("Content-Type", c.GetHeader("Content-Type"))
	req.ContentLength = c.Request.ContentLength

	resp, err := client.Do(req)
	if err != nil {
		logger.Logger.Error().Err(err).Str("agent", agentID).Msg("upload proxy: upstream request failed")
		c.JSON(http.StatusBadGateway, gin.H{"error": "upstream_unreachable"})
		return
	}
	defer resp.Body.Close()

	for k, vals := range resp.Header {
		for _, v := range vals {
			c.Header(k, v)
		}
	}
	c.Status(resp.StatusCode)
	io.Copy(c.Writer, resp.Body)
}

func (h *UploadProxyHandler) ProxyListFilesHandler(c *gin.Context) {
	agentID := c.Param("agentId")
	if agentID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "agentId is required"})
		return
	}

	agent, err := h.Storage.GetAgent(c.Request.Context(), agentID)
	if err != nil || agent == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "agent not found"})
		return
	}

	base := strings.TrimSpace(agent.BaseURL)
	if base == "" {
		c.JSON(http.StatusBadGateway, gin.H{"error": "agent_unreachable", "message": "agent has no base_url"})
		return
	}

	upstream := strings.TrimSuffix(base, "/") + "/files"

	client := &http.Client{Timeout: 10 * time.Second}
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodGet, upstream, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "proxy_request_failed"})
		return
	}

	resp, err := client.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "upstream_unreachable"})
		return
	}
	defer resp.Body.Close()

	c.Status(resp.StatusCode)
	c.Header("Content-Type", "application/json")
	io.Copy(c.Writer, resp.Body)
}
